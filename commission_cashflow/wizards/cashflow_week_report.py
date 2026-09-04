from datetime import date, timedelta
from html import escape

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import formatLang, format_date


class CommissionCashflowWeek(models.TransientModel):
    _name = "commission.cashflow.week"
    _description = "Weekly cashflow analysis"

    year = fields.Integer(required=True)
    week = fields.Integer(required=True)
    date_from = fields.Date(readonly=True)
    date_to = fields.Date(readonly=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        required=True,
        default=lambda self: self.env.company,
    )
    product_ids = fields.Many2many(
        comodel_name="product.product",
        string="Product Filter",
    )
    mail_partner_ids = fields.Many2many(
        comodel_name="res.partner",
        compute="_compute_mail_settings",
        inverse="_inverse_mail_settings",
        string="Recipients",
    )
    mail_product_ids = fields.Many2many(
        comodel_name="product.product",
        compute="_compute_mail_settings",
        inverse="_inverse_mail_settings",
        string="Default Filter for Monday Email",
        help="Leave empty for all products. Applies only to the automatic "
        "Monday email. The Send Email button uses the product filter above.",
    )
    mail_auto = fields.Boolean(
        compute="_compute_mail_settings",
        inverse="_inverse_mail_settings",
        string="Send every Monday",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    closing_count = fields.Integer(string="Closings")
    order_volume = fields.Monetary(string="Order Volume")
    cashflow_in = fields.Monetary(string="Cash-Flow In")
    product_revenue_ids = fields.One2many(
        comodel_name="commission.cashflow.week.line",
        inverse_name="report_id",
        domain=[("line_type", "=", "product_revenue")],
        string="Revenue by Product",
    )
    closer_revenue_ids = fields.One2many(
        comodel_name="commission.cashflow.week.line",
        inverse_name="report_id",
        domain=[("line_type", "=", "closer_revenue")],
        string="Revenue by Closer",
    )
    product_cashflow_ids = fields.One2many(
        comodel_name="commission.cashflow.week.line",
        inverse_name="report_id",
        domain=[("line_type", "=", "product_cashflow")],
        string="Cash-Flow by Product",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        iso = today.isocalendar()
        res.setdefault("year", iso.year)
        res.setdefault("week", iso.week)
        company = self.env.company
        if "product_ids" in fields_list and company.cashflow_week_mail_product_ids:
            res.setdefault(
                "product_ids",
                [(6, 0, company.cashflow_week_mail_product_ids.ids)],
            )
        return res

    @api.depends(
        "company_id",
        "company_id.cashflow_week_mail_partner_ids",
        "company_id.cashflow_week_mail_product_ids",
        "company_id.cashflow_week_mail_auto",
    )
    def _compute_mail_settings(self):
        for rec in self:
            company = rec.company_id
            rec.mail_partner_ids = company.cashflow_week_mail_partner_ids
            rec.mail_product_ids = company.cashflow_week_mail_product_ids
            rec.mail_auto = bool(company.cashflow_week_mail_auto)

    def _inverse_mail_settings(self):
        for rec in self:
            company = rec.company_id.sudo()
            if not company:
                continue
            company.cashflow_week_mail_partner_ids = rec.mail_partner_ids
            company.cashflow_week_mail_product_ids = rec.mail_product_ids
            company.cashflow_week_mail_auto = rec.mail_auto

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

    def _collect_week_data(self, date_from, date_to, product_ids):
        invoices = self.env["account.move"].search(
            [
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("company_id", "=", (self.company_id or self.env.company).id),
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

        def _sorted_items(mapping):
            return sorted(mapping.items(), key=lambda item: -item[1])

        return {
            "closing_count": closing_count,
            "order_volume": order_volume,
            "cashflow_in": cashflow_in,
            "product_revenue": _sorted_items(product_revenue),
            "closer_revenue": _sorted_items(closer_revenue),
            "product_cashflow": _sorted_items(product_cashflow),
        }

    def action_refresh(self):
        self.ensure_one()
        self._set_week_dates()
        self.env["commission.cashflow.week.line"].search(
            [("report_id", "=", self.id)]
        ).unlink()
        data = self._collect_week_data(
            self.date_from, self.date_to, self.product_ids
        )
        self.closing_count = data["closing_count"]
        self.order_volume = data["order_volume"]
        self.cashflow_in = data["cashflow_in"]
        vals_list = []
        for name, amount in data["product_revenue"]:
            vals_list.append(
                {
                    "report_id": self.id,
                    "line_type": "product_revenue",
                    "name": name,
                    "amount": amount,
                }
            )
        for name, amount in data["closer_revenue"]:
            vals_list.append(
                {
                    "report_id": self.id,
                    "line_type": "closer_revenue",
                    "name": name,
                    "amount": amount,
                }
            )
        for name, amount in data["product_cashflow"]:
            vals_list.append(
                {
                    "report_id": self.id,
                    "line_type": "product_cashflow",
                    "name": name,
                    "amount": amount,
                }
            )
        if vals_list:
            self.env["commission.cashflow.week.line"].create(vals_list)
        return self._reopen_form()

    def _reopen_form(self):
        """Reload this transient form. Odoo 19 requires an explicit views list."""
        self.ensure_one()
        action = self.env.ref(
            "commission_cashflow.action_commission_cashflow_week"
        )._get_action_dict()
        action["res_id"] = self.id
        action["views"] = [(False, "form")]
        action["view_mode"] = "form"
        action["target"] = "current"
        return action

    def _fmt_amount(self, amount):
        return formatLang(
            self.env, amount, currency_obj=self.currency_id or self.env.company.currency_id
        )

    def _fmt_section(self, title, items):
        if not items:
            return f"{title}\n{self.env._('No data')}"
        lines = [title]
        for name, amount in items:
            lines.append(f"    {name}: {self._fmt_amount(amount)}")
        return "\n".join(lines)

    def _mail_lang(self, partners=None):
        self.ensure_one()
        partners = partners if partners is not None else self.mail_partner_ids
        return (
            (partners[:1].lang if partners else False)
            or (self.company_id.partner_id.lang if self.company_id else False)
            or self.env.lang
        )

    def _render_week_email_body(self, data=None):
        self.ensure_one()
        if data is None:
            data = self._collect_week_data(
                self.date_from, self.date_to, self.product_ids
            )
        date_from = format_date(self.env, self.date_from)
        date_to = format_date(self.env, self.date_to)
        filter_names = ", ".join(self.product_ids.mapped("display_name"))
        body = self.env._(
            "%(year)s, CW: %(week)s\n"
            "Date: %(date_from)s - %(date_to)s\n"
            "Closings (contract date):\t%(closings)s\n"
            "Order volume:\t%(order_volume)s\n"
            "Cash-Flow In:\t%(cashflow_in)s\n"
            "%(product_revenue)s\n"
            "%(closer_revenue)s\n"
            "%(product_cashflow)s\n",
            year=self.year,
            week=self.week,
            date_from=date_from,
            date_to=date_to,
            closings=data["closing_count"],
            order_volume=self._fmt_amount(data["order_volume"]),
            cashflow_in=self._fmt_amount(data["cashflow_in"]),
            product_revenue=self._fmt_section(
                self.env._("📦 Revenue by product"), data["product_revenue"]
            ),
            closer_revenue=self._fmt_section(
                self.env._("👤 Revenue by closer"), data["closer_revenue"]
            ),
            product_cashflow=self._fmt_section(
                self.env._("💰 Cash-Flow by product"), data["product_cashflow"]
            ),
        )
        if filter_names:
            body += self.env._("\nFilter: %(filter)s\n", filter=filter_names)
        return body

    def _send_week_mail(self):
        self.ensure_one()
        partners = self.mail_partner_ids.filtered("email")
        if not partners:
            raise UserError(
                self.env._(
                    "Please set at least one recipient with an email address."
                )
            )
        self._set_week_dates()
        mailer = self.with_context(lang=self._mail_lang(partners))
        data = mailer._collect_week_data(
            self.date_from, self.date_to, self.product_ids
        )
        body = mailer._render_week_email_body(data)
        subject = mailer.env._(
            "Cashflow Week %(year)s, CW %(week)s",
            year=self.year,
            week=self.week,
        )
        body_html = (
            "<pre style='font-family: sans-serif; font-size: 14px; "
            "white-space: pre-wrap;'>%s</pre>" % escape(body)
        )
        company = self.company_id or self.env.company
        email_from = company.email or self.env.user.email or False
        self.env["mail.mail"].sudo().create(
            {
                "subject": subject,
                "body_html": body_html,
                "email_from": email_from,
                "email_to": ",".join(partners.mapped("email")),
                "auto_delete": True,
            }
        ).send()

    def action_send_mail(self):
        self.ensure_one()
        self.action_refresh()
        self._send_week_mail()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Email sent"),
                "message": self.env._("The weekly cashflow email was sent."),
                "type": "success",
                "sticky": False,
                "next": self._reopen_form(),
            },
        }

    @api.model
    def _cron_email_previous_week(self):
        today = fields.Date.context_today(self)
        iso = today.isocalendar()
        monday = date.fromisocalendar(iso.year, iso.week, 1)
        prev = monday - timedelta(days=1)
        prev_iso = prev.isocalendar()
        for company in self.env["res.company"].search(
            [("cashflow_week_mail_auto", "=", True)]
        ):
            partners = company.cashflow_week_mail_partner_ids.filtered("email")
            if not partners:
                continue
            report = self.with_company(company).create(
                {
                    "year": prev_iso.year,
                    "week": prev_iso.week,
                    "company_id": company.id,
                    "product_ids": [(6, 0, company.cashflow_week_mail_product_ids.ids)],
                    "currency_id": company.currency_id.id,
                }
            )
            report._set_week_dates()
            report._send_week_mail()


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
            ("product_revenue", "Revenue by Product"),
            ("closer_revenue", "Revenue by Closer"),
            ("product_cashflow", "Cash-Flow by Product"),
        ],
        required=True,
    )
    name = fields.Char(required=True)
    amount = fields.Monetary()
    currency_id = fields.Many2one(related="report_id.currency_id")
