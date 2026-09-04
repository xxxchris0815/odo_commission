def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE account_move
        ADD COLUMN IF NOT EXISTS contract_date DATE
        """
    )
