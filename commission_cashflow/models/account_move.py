from odoo import api, fields, models


class CommissionLineMixin(models.AbstractModel):
    _inherit = "commission.line.mixin"

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
            if record.agent_id and record.agent_role:
                commission = record.agent_id.get_commission_for_role(record.agent_role)
            if commission:
                record.commission_id = commission
            else:
                remaining |= record
        if remaining:
            super(CommissionLineMixin, remaining)._compute_commission_id()


class AccountInvoiceLineAgent(models.Model):
    _inherit = "account.invoice.line.agent"

    agent_role = fields.Selection(default="closer")

    cashflow_settled_amount = fields.Monetary(
        string="Already settled (cashflow)",
        default=0.0,
        help="Sum of commission amounts already settled via cashflow for this "
        "agent line. Used to compute the remaining commission on partial payments.",
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
        """Do not copy agents from the customer; keep lines already set."""
        for record in self:
            if (
                record.commission_free
                or not record.product_id
                or not record.move_id
                or record.move_id.move_type[:3] != "out"
            ) or not record.agent_ids:
                record.agent_ids = False

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
