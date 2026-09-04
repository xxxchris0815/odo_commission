def _add_column(cr, table, column, definition):
    cr.execute("SELECT to_regclass(%s)", (table,))
    if not cr.fetchone()[0]:
        return
    cr.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    if not cr.fetchone():
        cr.execute(
            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
        )


def _drop_unique_constraints(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    if not cr.fetchone()[0]:
        return
    cr.execute(
        """
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        WHERE t.relname = %s
          AND c.contype = 'u'
        """,
        (table,),
    )
    for (conname,) in cr.fetchall():
        cr.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{conname}"')


def migrate(cr, version):
    _add_column(cr, "account_invoice_line_agent", "agent_role", "VARCHAR")
    _add_column(
        cr, "account_invoice_line_agent", "cashflow_settled_amount", "NUMERIC"
    )
    for table in ("account_invoice_line_agent", "sale_order_line_agent"):
        _drop_unique_constraints(cr, table)
