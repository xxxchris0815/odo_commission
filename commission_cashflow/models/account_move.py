from odoo import api, exceptions, fields, models
from odoo.fields import Command


class CommissionLineMixin(models.AbstractModel):
    _inherit = "commission.line.mixin"

    # OCA uses UNIQUE(object_id, agent_id). The same person must be allowed
    # as Opener and Closer on one line. A no-op CHECK replaces that unique
    # constraint so registry init cannot fail on existing duplicates.
    _unique_agent = models.Constraint(
        "CHECK(1=1)",
        "Same agent may appear once per role.",
    )

    agent_role = fields.Selection(
        [
            ("opener", "Opener"),
            ("closer", "Closer"),
            ("partner", "Partner"),
        ],
        string="Role",
        default="closer",
    )

    @api.depends("agent_id", "agent_role")
    def _compute_commission_id(self):
        remaining = self.browse()
        for record in self:
            commission = self.env["commission"]
            try:
                if record.agent_id and record.agent_role:
                    commission = record.agent_id.get_commission_for_role(
                        record.agent_role
                    )
            except Exception:
                commission = self.env["commission"]
            if commission:
                record.commission_id = commission
            else:
                remaining |= record
        if remaining:
            super(CommissionLineMixin, remaining)._compute_commission_id()


class AccountInvoiceLineAgent(models.Model):
    _inherit = "account.invoice.line.agent"

    _unique_agent = models.Constraint(
        "CHECK(1=1)",
        "Same agent may appear once per role.",
    )

    agent_role = fields.Selection(
        [
            ("opener", "Opener"),
            ("closer", "Closer"),
            ("partner", "Partner"),
        ],
        string="Role",
        default="closer",
    )

    cashflow_settled_amount = fields.Monetary(
        string="Already settled (cashflow)",
        default=0.0,
        help="Sum of commission amounts already settled via cashflow for this "
        "agent line. Used to compute the remaining commission on partial payments.",
    )

    @api.constrains("object_id", "agent_id", "agent_role")
    def _check_unique_agent_role(self):
        for rec in self:
            if not rec.object_id or not rec.agent_id:
                continue
            duplicates = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("object_id", "=", rec.object_id.id),
                    ("agent_id", "=", rec.agent_id.id),
                    ("agent_role", "=", rec.agent_role),
                ]
            )
            if duplicates:
                raise exceptions.ValidationError(
                    self.env._(
                        "Agent %(agent)s is already assigned as %(role)s "
                        "on this invoice line.",
                        agent=rec.agent_id.display_name,
                        role=dict(rec._fields["agent_role"].selection).get(
                            rec.agent_role, rec.agent_role
                        ),
                    )
                )

    def _get_cashflow_commission(self, payment_ratio):
        """Return the commission amount proportional to the payment received.

        :param payment_ratio: float between 0 and 1 representing the share
            of the invoice that has been paid in the current period.
        :return: commission amount for this payment slice.
        """
        self.ensure_one()
        total_commission = self.amount
        already_settled = self.cashflow_settled_amount
        remaining = total_commission - already_settled
        proportional = total_commission * payment_ratio
        return min(proportional, remaining)

    def _skip_settlement(self):
        """Override: for cashflow settlements we handle the paid-check in the
        wizard, so never skip based on payment_state here."""
        if self.env.context.get("cashflow_settlement"):
            return self.invoice_id.state != "posted"
        return super()._skip_settlement()


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.depends("move_id.partner_id")
    def _compute_agent_ids(self):
        """Never copy customer agents. Always assign agent_ids."""
        for record in self:
            move_type = record.move_id.move_type if record.move_id else ""
            wipe = (
                record.commission_free
                or not record.product_id
                or not record.move_id
                or (move_type or "")[:3] != "out"
            )
            # Keep agents already on the line; empty stays empty.
            # Always assign so Odoo 19 does not fail the compute.
            record.agent_ids = (
                False if wipe else [Command.set(record.agent_ids.ids)]
            )

    def _prepare_agents_vals_partner(self, partner, settlement_type=None):
        """Do not auto-copy customer-level agents onto invoice lines."""
        return []

    def _prepare_agent_vals(self, agent):
        vals = super()._prepare_agent_vals(agent)
        roles = agent.commission_role_ids
        if len(roles) == 1:
            vals["agent_role"] = roles.role
            vals["commission_id"] = roles.commission_id.id
            return vals
        closer = agent.get_commission_for_role("closer")
        vals["agent_role"] = "closer"
        if closer:
            vals["commission_id"] = closer.id
        return vals


class AccountPayment(models.Model):
    _inherit = "account.payment"

    @api.model
    def _get_cashflow_ratio_for_invoice(self, payment, invoice):
        """Compute what share of the invoice total this payment covers."""
        if not invoice.amount_total:
            return 0.0
        reconciled = 0.0
        for partial in invoice.line_ids.matched_debit_ids:
            if partial.debit_move_id.payment_id == payment:
                reconciled += partial.amount
        for partial in invoice.line_ids.matched_credit_ids:
            if partial.credit_move_id.payment_id == payment:
                reconciled += partial.amount
        return min(reconciled / invoice.amount_total, 1.0)
