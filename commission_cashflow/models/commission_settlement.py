from odoo import fields, models


class CommissionSettlement(models.Model):
    _inherit = "commission.settlement"

    settlement_type = fields.Selection(
        selection_add=[("cashflow", "Cashflow (Payments)")],
        ondelete={"cashflow": "set default"},
    )

    def _compute_can_edit(self):
        cashflow = self.filtered(lambda x: x.settlement_type == "cashflow")
        cashflow.update({"can_edit": False})
        return super(CommissionSettlement, self - cashflow)._compute_can_edit()
