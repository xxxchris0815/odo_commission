

from odoo import fields, models
from odoo.fields import Domain


class CommissionMakeSettle(models.TransientModel):
    _inherit = "commission.make.settle"

    settlement_type = fields.Selection(
        selection_add=[("cashflow", "Cashflow (Payments)")],
        ondelete={"cashflow": "cascade"},
    )

    def _get_cashflow_agent_lines(self, agent, date_to_agent):
        """Return invoice agent lines that have at least partial payment
        in the relevant period and are not yet fully settled via cashflow."""
        domain = Domain.AND(
            [
                Domain("agent_id", "=", agent.id),
                Domain("settled", "=", False),
                Domain("invoice_id.state", "=", "posted"),
                Domain("object_id.display_type", "=", "product"),
                Domain("invoice_date", "<", date_to_agent),
            ]
        )
        candidates = self.env["account.invoice.line.agent"].search(
            domain, order="invoice_date"
        )
        result = self.env["account.invoice.line.agent"]
        for line in candidates:
            invoice = line.invoice_id
            if invoice.payment_state in ("partial", "in_payment", "paid", "reversed"):
                result |= line
        return result

    def _get_agent_lines(self, agent, date_to_agent):
        if self.settlement_type != "cashflow":
            return super()._get_agent_lines(agent, date_to_agent)
        return self._get_cashflow_agent_lines(agent, date_to_agent)

    def _prepare_settlement_line_vals(self, settlement, line):
        if self.settlement_type != "cashflow":
            return super()._prepare_settlement_line_vals(settlement, line)
        invoice = line.invoice_id
        paid_amount = invoice.amount_total - invoice.amount_residual
        if invoice.amount_total:
            payment_ratio = min(paid_amount / invoice.amount_total, 1.0)
        else:
            payment_ratio = 0.0

        cashflow_amount = line._get_cashflow_commission(payment_ratio)

        line.cashflow_settled_amount += cashflow_amount

        if abs(line.cashflow_settled_amount - line.amount) < 0.01:
            line.settled = True

        return {
            "settlement_id": settlement.id,
            "invoice_agent_line_id": line.id,
            "date": fields.Date.today(),
            "commission_id": line.commission_id.id,
            "settled_amount": cashflow_amount,
        }

    def action_settle(self):
        if self.settlement_type == "cashflow":
            return super().with_context(cashflow_settlement=True).action_settle()
        return super().action_settle()
