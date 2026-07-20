DO $rollback_gate$
DECLARE
    unsafe_demo_present boolean := false;
BEGIN
    IF to_regclass('public.user_accounts') IS NOT NULL THEN
        EXECUTE
            'SELECT EXISTS ('
            'SELECT 1 FROM user_accounts '
            'WHERE (actor_ref = $1 AND status = $2) '
            'OR actor_ref LIKE $3'
            ')'
        INTO unsafe_demo_present
        USING 'demo:public', 'ACTIVE', 'demo:role:%';
    END IF;

    IF unsafe_demo_present THEN
        RAISE EXCEPTION
            'public demo accounts block rollback to an image without demo guards';
    END IF;
END
$rollback_gate$;
