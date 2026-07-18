DO $rollback_gate$
DECLARE
    demo_active boolean := false;
BEGIN
    IF to_regclass('public.user_accounts') IS NOT NULL THEN
        EXECUTE
            'SELECT EXISTS ('
            'SELECT 1 FROM user_accounts '
            'WHERE actor_ref = $1 AND status = $2'
            ')'
        INTO demo_active
        USING 'demo:public', 'ACTIVE';
    END IF;

    IF demo_active THEN
        RAISE EXCEPTION
            'active public demo account blocks rollback to an image without demo guards';
    END IF;
END
$rollback_gate$;
