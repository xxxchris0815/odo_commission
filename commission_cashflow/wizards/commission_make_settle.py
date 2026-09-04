from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields, models


class CommissionMakeSettle(models.TransientModel):
    _inherit = "commission.make.settle"

    settlement_type = fields.Selection(
        selection_add=[("cashflow", "Cashflow (Payments)")],
        ondelete={"cashflow": "cascade"},
    )

    def _get_period_start(self, agent, date_to):
        res = super()._get_period_start(agent, date_to)
        if res or not date_to:
            return res
        # Agents without a settlement period still get a monthly window.
        return date(year=date_to.year, month=date_to.month, day=1)

    def _get_next_period_date(self, agent, current_date):
        res = super()._get_next_period_date(agent, current_date)
        if res or not current_date:
            return res
        return current_date + relativedelta(months=1)

    def _get_cashflow_agent_lines(self, agent, date_to_agent):
        """Return opener/closer lines with an unpaid cashflow remainder.

        Do not use the stored `settled` flag: leftover values from earlier
        test settlements hid Klara/Sabrina while Partner still ran.
        """
        date_limit = self.date_to or date_to_agent
        candidates = self.env["account.invoice.line.agent"].search(
            [
                ("agent_id", "=", agent.id),
                ("invoice_id.state", "=", "posted"),
            ],
            order="invoice_date",
        )
        result = self.env["account.invoice.line.agent"]
        for line in candidates:
            if line._is_monthly_partner_staffel():
                continue
            display = line.object_id.display_type
            if display in ("line_section", "line_note"):
                continue
            if date_limit and line.invoice_date and line.invoice_date > date_limit:
                continue
            invoice = line.invoice_id
            paid = invoice.amount_total - invoice.amount_residual
            if invoice.amount_total:
                ratio = min(paid / invoice.amount_total, 1.0)
            else:
                ratio = 0.0
            if line._get_cashflow_commission(ratio) > 0.01:
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

        return {
            "settlement_id": settlement.id,
            "invoice_agent_line_id": line.id,
            "date": fields.Date.today(),
            "commission_id": line.commission_id.id,
            "settled_amount": cashflow_amount,
        }

    def _calculate_partner_staffel(self, commission, volume):
        """Apply section rates to the monthly cashflow volume.

        Uses the bracket that contains the volume. If volume is above the
        last cap, the last section's percentage applies to the full volume.
        """
        sections = commission.section_ids.sorted("amount_from")
        if not sections or volume <= 0:
            return 0.0
        for section in sections:
            if section.amount_from <= volume <= section.amount_to:
                return volume * section.percent / 100.0
        last = sections[-1]
        if volume > last.amount_to:
            return volume * last.percent / 100.0
        return 0.0

    def _partner_staffel_already_settled(self, lines, sett_from, sett_to):
        settlement_lines = self.env["commission.settlement.line"].search(
            [
                ("invoice_agent_line_id", "in", lines.ids),
                ("settlement_id.date_from", "=", sett_from),
                ("settlement_id.date_to", "=", sett_to),
                ("settlement_id.state", "!=", "cancel"),
            ]
        )
        already = {}
        for sl in settlement_lines:
            already.setdefault(sl.invoice_agent_line_id.id, 0.0)
            already[sl.invoice_agent_line_id.id] += sl.settled_amount
        return already

    def _settle_partner_monthly_staffel(self):
        """Settle Partner section commissions on monthly cashflow volume.

        All posted invoices where the agent is Partner with a staffel
        (By sections) are included. Payments whose date falls in the
        agent's settlement period are summed; the staffel is applied to
        that total, then split across invoices by their share of the
        volume. Re-running the wizard true-ups if later payments in the
        same month reach a higher bracket.
        """
        self.ensure_one()
        agents = self.agent_ids or self.env["res.partner"].search(
            [("agent", "=", True)]
        )
        settlement_obj = self.env["commission.settlement"]
        settlement_line_obj = self.env["commission.settlement.line"]
        settlement_ids = []
        for agent in agents:
            sett_from = self._get_period_start(agent, self.date_to)
            if not sett_from:
                continue
            sett_to = self._get_next_period_date(agent, sett_from) - timedelta(days=1)
            cashflow_to = min(sett_to, self.date_to)
            partner_lines = self.env["account.invoice.line.agent"].search(
                [
                    ("agent_id", "=", agent.id),
                    ("agent_role", "=", "partner"),
                    ("commission_id.commission_type", "=", "section"),
                    ("invoice_id.state", "=", "posted"),
                    ("invoice_id.move_type", "=", "out_invoice"),
                    ("object_id.display_type", "=", "product"),
                ]
            )
            if not partner_lines:
                continue
            by_company = {}
            for line in partner_lines:
                key = (line.company_id.id, line.currency_id.id)
                by_company.setdefault(key, self.env["account.invoice.line.agent"])
                by_company[key] |= line
            for (company_id, currency_id), lines in by_company.items():
                paid_by_invoice = {}
                lines_by_invoice = {}
                for line in lines:
                    inv_id = line.invoice_id.id
                    lines_by_invoice.setdefault(
                        inv_id, self.env["account.invoice.line.agent"]
                    )
                    lines_by_invoice[inv_id] |= line
                    if inv_id not in paid_by_invoice:
                        paid_by_invoice[inv_id] = line.invoice_id._get_cashflow_in_period(
                            sett_from, cashflow_to
                        )
                volume = sum(paid_by_invoice.values())
                commission = lines[:1].commission_id
                total_commission = self._calculate_partner_staffel(commission, volume)
                already = self._partner_staffel_already_settled(
                    lines, sett_from, sett_to
                )
                line_vals = []
                company = self.env["res.company"].browse(company_id)
                currency = self.env["res.currency"].browse(currency_id)
                settlement = False
                for inv_id, inv_lines in lines_by_invoice.items():
                    paid = paid_by_invoice[inv_id]
                    target = total_commission * (paid / volume) if volume else 0.0
                    already_invoice = sum(already.get(line.id, 0.0) for line in inv_lines)
                    incremental = target - already_invoice
                    if abs(incremental) < 0.01:
                        continue
                    if not settlement:
                        settlement = self._get_settlement(
                            agent, company, currency, sett_from, sett_to
                        )
                        if not settlement:
                            settlement = settlement_obj.create(
                                self._prepare_settlement_vals(
                                    agent, company, sett_from, sett_to
                                )
                            )
                            settlement.currency_id = currency
                        settlement_ids.append(settlement.id)
                    weights = [line.object_id.price_subtotal for line in inv_lines]
                    weight_sum = sum(weights) or len(inv_lines)
                    for line, weight in zip(inv_lines, weights, strict=True):
                        share = incremental * (
                            (weight / weight_sum) if weight_sum else 0.0
                        )
                        if abs(share) < 0.01:
                            continue
                        line_vals.append(
                            {
                                "settlement_id": settlement.id,
                                "invoice_agent_line_id": line.id,
                                "date": fields.Date.today(),
                                "commission_id": line.commission_id.id,
                                "settled_amount": share,
                            }
                        )
                if line_vals:
                    settlement_line_obj.create(line_vals)
        return settlement_ids

    def action_settle(self):
        if self.settlement_type != "cashflow":
            return super().action_settle()
        # Bind context first, then call the parent. Do not use
        # super().with_context(...).action_settle() — that re-enters this
        # method and overflows the stack.
        self = self.with_context(cashflow_settlement=True)
        res = super().action_settle()
        extra_ids = self._settle_partner_monthly_staffel()
        if not extra_ids:
            return res
        if isinstance(res, dict) and res.get("domain"):
            existing = []
            for leaf in res["domain"]:
                if (
                    isinstance(leaf, (list, tuple))
                    and len(leaf) == 3
                    and leaf[0] == "id"
                    and leaf[1] == "in"
                ):
                    existing = list(leaf[2])
                    break
            res["domain"] = [["id", "in", existing + extra_ids]]
            return res
        return {
            "name": self.env._("Created Settlements"),
            "type": "ir.actions.act_window",
            "views": [[False, "list"], [False, "form"]],
            "res_model": "commission.settlement",
            "domain": [["id", "in", extra_ids]],
        }
