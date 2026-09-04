def _drop_old_unique_agent(cr, table):
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
          AND replace(pg_get_constraintdef(c.oid), ' ', '')
              = 'UNIQUE(object_id,agent_id)'
        """,
        (table,),
    )
    for (conname,) in cr.fetchall():
        cr.execute(
            f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{conname}"'
        )


def migrate(cr, version):
    for table in ("account_invoice_line_agent", "sale_order_line_agent"):
        _drop_old_unique_agent(cr, table)
