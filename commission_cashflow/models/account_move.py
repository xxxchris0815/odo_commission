from odoo import api, exceptions, fields, models
from odoo.fields import Command


def _ensure_column(cr, table, column, definition):
    """Add a DB column on restart so git pull without -u cannot crash Odoo."""
    cr.execute(
        f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {definition}'
    )


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
    )

    def _register_hook(self):
        _ensure_column(self.env.cr, "account_invoice_line_agent", "agent_role", "VARCHAR")
        _ensure_column(
            self.env.cr,
            "account_invoice_line_agent",
            "cashflow_settled_amount",
            "NUMERIC",
        )
        return super()._register_hook()

    cashflow_settled_amount = fields.Monetary(
        string="Already settled (cashflow)",
        compute="_compute_cashflow_settled_amount",
        store=True,
        help="Sum of non-cancelled cashflow settlement lines for this agent "
        "line. Deleting a settlement resets this automatically.",
    )
    monthly_staffel = fields.Boolean(
        compute="_compute_monthly_staffel",
        help="Partner staffel uses monthly cashflow across all invoices, "
        "not this invoice amount.",
    )

    @api.depends("agent_role", "commission_id", "commission_id.commission_type")
    def _compute_monthly_staffel(self):
        for rec in self:
            rec.monthly_staffel = rec._is_monthly_partner_staffel()

    @api.depends(
        "settlement_line_ids.settled_amount",
        "settlement_line_ids.settlement_id.state",
    )
    def _compute_cashflow_settled_amount(self):
        for line in self:
            line.cashflow_settled_amount = line._cashflow_already_settled()

    @api.depends(
        "settlement_line_ids",
        "settlement_line_ids.settlement_id.state",
        "settlement_line_ids.settled_amount",
        "invoice_id",
        "invoice_id.state",
        "amount",
        "agent_role",
        "commission_id",
        "cashflow_settled_amount",
    )
    def _compute_settled(self):
        """Keep the line open until cashflow has paid the full commission.

        OCA marks a line settled as soon as any settlement line exists, which
        blocks later payments and leaves a stale counter after deletions.
        """
        for line in self:
            already = line._cashflow_already_settled()
            if line._is_monthly_partner_staffel():
                line.settled = False
                continue
            if abs(line.amount) > 0.01 and already + 0.01 < abs(line.amount):
                line.settled = False
            else:
                line.settled = any(
                    sl.settlement_id.state != "cancel"
                    for sl in line.settlement_line_ids
                )

    def _used_roles_for_agent(self, object_id, agent_id, exclude=None):
        domain = [
            ("object_id", "=", object_id),
            ("agent_id", "=", agent_id),
        ]
        if exclude:
            domain.append(("id", "not in", exclude.ids))
        return set(self.search(domain).mapped("agent_role"))

    def _next_free_role(self, used):
        for role in ("opener", "closer", "partner"):
            if role not in used:
                return role
        return False

    @api.onchange("agent_id")
    def _onchange_agent_id_pick_role(self):
        if not self.agent_id or not self.object_id:
            return
        used = set(
            self.object_id.agent_ids.filtered(
                lambda line: line.agent_id == self.agent_id and line != self
            ).mapped("agent_role")
        )
        if not self.agent_role or self.agent_role in used:
            self.agent_role = self._next_free_role(used)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            agent_id = vals.get("agent_id")
            object_id = vals.get("object_id")
            if not agent_id or not object_id:
                continue
            used = self._used_roles_for_agent(object_id, agent_id)
            role = vals.get("agent_role")
            if not role or role in used:
                nxt = self._next_free_role(used)
                if nxt:
                    vals["agent_role"] = nxt
        return super().create(vals_list)

    @api.constrains("object_id", "agent_id", "agent_role")
    def _check_unique_agent_role(self):
        for rec in self:
            if not rec.object_id or not rec.agent_id or not rec.agent_role:
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
                        "on this invoice line. Use a different role "
                        "(Opener, Closer, Partner).",
                        agent=rec.agent_id.display_name,
                        role=dict(rec._fields["agent_role"].selection).get(
                            rec.agent_role, rec.agent_role
                        ),
                    )
                )

    def _is_monthly_partner_staffel(self):
        self.ensure_one()
        return (
            self.agent_role == "partner"
            and self.commission_id
            and self.commission_id.commission_type == "section"
        )

    def _cashflow_already_settled(self):
        """Sum live settlement lines so deleted/cancelled docs do not linger."""
        self.ensure_one()
        return sum(
            self.settlement_line_ids.filtered(
                lambda sl: sl.settlement_id.state != "cancel"
            ).mapped("settled_amount")
        )

    def _get_cashflow_commission(self, payment_ratio):
        """Return the commission amount proportional to the payment received.

        :param payment_ratio: float between 0 and 1 representing the share
            of the invoice that has been paid in the current period.
        :return: commission amount for this payment slice.
        """
        self.ensure_one()
        if self._is_monthly_partner_staffel():
            return 0.0
        total_commission = self.amount
        already_settled = self._cashflow_already_settled()
        target = total_commission * payment_ratio
        return max(0.0, min(target, total_commission) - already_settled)

    @api.depends(
        "object_id.price_subtotal",
        "object_id.commission_free",
        "commission_id",
        "agent_role",
    )
    def _compute_amount(self):
        monthly = self.filtered(lambda line: line._is_monthly_partner_staffel())
        others = self - monthly
        if others:
            super(AccountInvoiceLineAgent, others)._compute_amount()
        for line in monthly:
            # Staffel is applied to monthly cashflow at settlement, not
            # to this single invoice line (which would often be 0).
            line.amount = 0.0

    def _skip_settlement(self):
        """Override: for cashflow settlements we handle the paid-check in the
        wizard, so never skip based on payment_state here."""
        if self.env.context.get("cashflow_settlement"):
            return self.invoice_id.state != "posted"
        return super()._skip_settlement()


class AccountMove(models.Model):
    _inherit = "account.move"

    contract_date = fields.Date(
        string="Contract Date",
        help="Date the deal was closed. Weekly closings and order volume "
        "use this date. Cashflow uses the payment date. If empty, the "
        "invoice date is used.",
        copy=False,
    )

    def _register_hook(self):
        _ensure_column(self.env.cr, "account_move", "contract_date", "DATE")
        return super()._register_hook()

    def _effective_contract_date(self):
        self.ensure_one()
        return self.contract_date or self.invoice_date

    def _get_cashflow_in_period(self, date_from, date_to):
        """Sum of payment amounts reconciled on this invoice in the date range."""
        self.ensure_one()
        total = 0.0
        receivable = self.line_ids.filtered(
            lambda line: line.account_id.account_type == "asset_receivable"
        )
        for inv_line in receivable:
            partials = inv_line.matched_credit_ids | inv_line.matched_debit_ids
            for partial in partials:
                counterpart = (
                    partial.credit_move_id
                    if partial.debit_move_id == inv_line
                    else partial.debit_move_id
                )
                pay_date = (
                    counterpart.payment_id.date
                    if counterpart.payment_id
                    else counterpart.date
                )
                if date_from and date_to and date_from <= pay_date <= date_to:
                    total += partial.amount
        return total


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.depends(
        "commission_free",
        "agent_ids",
        "agent_ids.agent_id",
        "agent_ids.agent_role",
    )
    def _compute_commission_status(self):
        role_labels = dict(
            self.env["account.invoice.line.agent"]
            .fields_get(["agent_role"])["agent_role"]["selection"]
        )
        remaining = self.browse()
        for line in self:
            if line.commission_free:
                line.commission_status = self.env._("Comm. free")
                continue
            parts = []
            for agent_line in line.agent_ids:
                name = agent_line.agent_id.display_name or ""
                role = role_labels.get(agent_line.agent_role) or agent_line.agent_role
                if name and role:
                    parts.append(f"{name} ({role})")
                elif name:
                    parts.append(name)
            if parts:
                line.commission_status = ", ".join(parts)
            else:
                remaining |= line
        if remaining:
            super(AccountMoveLine, remaining)._compute_commission_status()

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
