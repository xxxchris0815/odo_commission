from datetime import date, timedelta

from odoo import api, fields, models


class CommissionCashflowWeek(models.TransientModel):
    _name = "commission.cashflow.week"
    _description = "Weekly cashflow analysis"

    year = fields.Integer(required=True)
    week = fields.Integer(required=True)
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Product filter",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    closing_count = fields.Integer(string="Closings (contract date)")
    order_volume = fields.Monetary(string="Order volume")
    cashflow_in = fields.Monetary(string="Cash-Flow In")
    product_revenue_ids = fields.One2many(
        comodel_name="commission.cashflow.week.line",
        inverse_name="report_id",
        domain=[("line_type", "=", "product_revenue")],
        string="Revenue by product",
    )
    closer_revenue_ids = fields.One2many(
        comodel_name="commission.cashflow.week.line",
        inverse_name="report_id",
        domain=[("line_type", "=", "closer_revenue")],
        string="Revenue by closer",
    )
    product_cashflow_ids = fields.One2many(
        comodel_name="commission.cashflow.week.line",
        inverse_name="report_id",
        domain=[("line_type", "=", "product_cashflow")],
        string="Cash-Flow by product",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        iso = today.isocalendar()
        res.setdefault("year", iso.year)
        res.setdefault("week", iso.week)
        return res

    @api.onchange("year", "week")
    def _onchange_week(self):
        self._set_week_dates()

    def _set_week_dates(self):
        for rec in self:
            year = rec.year or date.today().isocalendar().year
            week = rec.week or 1
            week = min(max(int(week), 1), 53)
            rec.week = week
            rec.year = year
            try:
                monday = date.fromisocalendar(year, week, 1)
            except ValueError:
                monday = date.fromisocalendar(year, 52, 1)
                rec.week = 52
            rec.date_from = monday
            rec.date_to = monday + timedelta(days=6)

    def action_prev_week(self):
        self.ensure_one()
        self._set_week_dates()
        prev_day = self.date_from - timedelta(days=1)
        iso = prev_day.isocalendar()
        self.write({"year": iso.year, "week": iso.week})
        self._set_week_dates()
        return self.action_refresh()

    def action_next_week(self):
        self.ensure_one()
        self._set_week_dates()
        next_day = self.date_to + timedelta(days=1)
        iso = next_day.isocalendar()
        self.write({"year": iso.year, "week": iso.week})
        self._set_week_dates()
        return self.action_refresh()

    def action_refresh(self):
        self.ensure_one()
        self._set_week_dates()
        self.env["commission.cashflow.week.line"].search(
            [("report_id", "=", self.id)]
        ).unlink()
        date_from = self.date_from
        date_to = self.date_to
        product_ids = self.product_ids
        invoices = self.env["account.move"].search(
            [
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
            ]
        )
        closing_invoices = invoices.filtered(
            lambda inv: inv._effective_contract_date()
            and date_from <= inv._effective_contract_date() <= date_to
        )
        product_revenue = {}
        closer_revenue = {}
        closing_count = 0
        order_volume = 0.0
        for inv in closing_invoices:
            lines = inv.invoice_line_ids.filtered(
                lambda line: line.display_type not in ("line_section", "line_note")
            )
            if product_ids:
                lines = lines.filtered(lambda line: line.product_id in product_ids)
                if not lines:
                    continue
            closing_count += 1
            order_volume += sum(lines.mapped("price_subtotal"))
            for line in lines:
                pname = line.product_id.display_name or line.name or "/"
                product_revenue[pname] = (
                    product_revenue.get(pname, 0.0) + line.price_subtotal
                )
                closers = line.agent_ids.filtered(lambda a: a.agent_role == "closer")
                if not closers:
                    closer_name = self.env._("No closer")
                    closer_revenue[closer_name] = (
                        closer_revenue.get(closer_name, 0.0) + line.price_subtotal
                    )
                else:
                    share = line.price_subtotal / len(closers)
                    for closer in closers:
                        cname = closer.agent_id.display_name
                        closer_revenue[cname] = closer_revenue.get(cname, 0.0) + share

        product_cashflow = {}
        cashflow_in = 0.0
        for inv in invoices:
            paid = inv._get_cashflow_in_period(date_from, date_to)
            if paid <= 0.01:
                continue
            all_lines = inv.invoice_line_ids.filtered(
                lambda line: line.display_type not in ("line_section", "line_note")
            )
            base = sum(all_lines.mapped("price_subtotal"))
            if base <= 0:
                if not product_ids:
                    cashflow_in += paid
                continue
            lines = all_lines
            if product_ids:
                lines = all_lines.filtered(lambda line: line.product_id in product_ids)
                if not lines:
                    continue
                paid = paid * (sum(lines.mapped("price_subtotal")) / base)
            cashflow_in += paid
            line_base = sum(lines.mapped("price_subtotal")) or 1.0
            for line in lines:
                pname = line.product_id.display_name or line.name or "/"
                share = paid * (line.price_subtotal / line_base)
                product_cashflow[pname] = product_cashflow.get(pname, 0.0) + share

        self.closing_count = closing_count
        self.order_volume = order_volume
        self.cashflow_in = cashflow_in
        Line = self.env["commission.cashflow.week.line"]
        vals_list = []
        for name, amount in sorted(product_revenue.items(), key=lambda i: -i[1]):
            vals_list.append(
                {
                    "report_id": self.id,
                    "line_type": "product_revenue",
                    "name": name,
                    "amount": amount,
                }
            )
        for name, amount in sorted(closer_revenue.items(), key=lambda i: -i[1]):
            vals_list.append(
                {
                    "report_id": self.id,
                    "line_type": "closer_revenue",
                    "name": name,
                    "amount": amount,
                }
            )
        for name, amount in sorted(product_cashflow.items(), key=lambda i: -i[1]):
            vals_list.append(
                {
                    "report_id": self.id,
                    "line_type": "product_cashflow",
                    "name": name,
                    "amount": amount,
                }
            )
        if vals_list:
            Line.create(vals_list)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }


class CommissionCashflowWeekLine(models.TransientModel):
    _name = "commission.cashflow.week.line"
    _description = "Weekly cashflow analysis line"
    _order = "amount desc, id"

    report_id = fields.Many2one(
        comodel_name="commission.cashflow.week",
        ondelete="cascade",
        required=True,
    )
    line_type = fields.Selection(
        [
            ("product_revenue", "Revenue by product"),
            ("closer_revenue", "Revenue by closer"),
            ("product_cashflow", "Cash-Flow by product"),
        ],
        required=True,
    )
    name = fields.Char(required=True)
    amount = fields.Monetary()
    currency_id = fields.Many2one(related="report_id.currency_id")
