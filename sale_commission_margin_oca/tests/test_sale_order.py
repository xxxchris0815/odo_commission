# Copyright 2025 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import Command
from odoo.tests import tagged

from odoo.addons.base.tests.common import BaseCommon


@tagged("post_install", "-at_install")
class TestSaleOrder(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.product = cls.env["product.product"].create(
            {
                "name": "Product",
                "type": "consu",
                "list_price": 100,
                "standard_price": 50,
            }
        )

        cls.commission = cls.env["commission"].create(
            {
                "name": "10% Commission",
                "commission_type": "fixed",
                "amount_base_type": "gross_amount",
                "invoice_state": "open",
                "fix_qty": 10,
            }
        )

        cls.agent = cls.env["res.partner"].create(
            {
                "name": "Agent",
                "agent": True,
                "agent_type": "agent",
                "commission_id": cls.commission.id,
                "settlement": "monthly",
            }
        )
        cls.partner = cls.env["res.partner"].create({"name": "Customer"})

    def test_sale_order_with_commission(self):
        """
        Data:
            Price: 100
            Cost: 50
            Commission: 10%

        Result:
            Sale Order Total: 100
            Sale Order Commission: 10
            Sale Order Margin: 40"""

        sale_order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "order_line": [
                    Command.create(
                        {
                            "product_id": self.product.id,
                            "product_uom_qty": 1,
                            "price_unit": 100,
                        }
                    )
                ],
            }
        )
        sale_agent = self.env["sale.order.line.agent"].create(
            {
                "object_id": sale_order.order_line[0].id,
                "commission_id": self.commission.id,
                "agent_id": self.agent.id,
            }
        )
        sale_order.order_line[0].agent_ids = [Command.link(sale_agent.id)]

        self.assertEqual(sale_order.amount_untaxed, 100.0)
        self.assertEqual(sale_order.commission_total, 10.0)
        self.assertEqual(sale_order.margin, 40.0)
        self.assertEqual(sale_order.margin_percent, 0.4)
