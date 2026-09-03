from odoo import api, fields, models


class AccountInvoiceLineAgent(models.Model):
    _inherit = "account.invoice.line.agent"

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
