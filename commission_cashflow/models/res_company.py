from odoo import fields, models

from .account_move import _ensure_column


class ResCompany(models.Model):
    _inherit = "res.company"

    cashflow_week_mail_partner_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="res_company_cashflow_week_mail_partner_rel",
        column1="company_id",
        column2="partner_id",
        string="Weekly cashflow mail to",
    )
    cashflow_week_mail_product_ids = fields.Many2many(
        comodel_name="product.product",
        relation="res_company_cashflow_week_mail_product_rel",
        column1="company_id",
        column2="product_id",
        string="Weekly cashflow product filter",
    )
    cashflow_week_mail_auto = fields.Boolean(
        string="Email weekly cashflow automatically",
        help="Every Monday, send the previous ISO week to the recipients. "
        "No mail is sent if this is off or if no recipient has an email.",
    )

    def _register_hook(self):
        cr = self.env.cr
        _ensure_column(cr, "res_company", "cashflow_week_mail_auto", "BOOLEAN")
        cr.execute(
            """
            CREATE TABLE IF NOT EXISTS res_company_cashflow_week_mail_partner_rel (
                company_id INTEGER NOT NULL REFERENCES res_company(id) ON DELETE CASCADE,
                partner_id INTEGER NOT NULL REFERENCES res_partner(id) ON DELETE CASCADE,
                PRIMARY KEY (company_id, partner_id)
            )
            """
        )
        cr.execute(
            """
            CREATE TABLE IF NOT EXISTS res_company_cashflow_week_mail_product_rel (
                company_id INTEGER NOT NULL REFERENCES res_company(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES product_product(id) ON DELETE CASCADE,
                PRIMARY KEY (company_id, product_id)
            )
            """
        )
        return super()._register_hook()
