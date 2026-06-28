INSERT INTO dc.dc_modules_action
  (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT
  'live.strategyListView',
  '查看当前运行实盘策略',
  'live',
  'WEB',
  NULL,
  'system',
  '查看当前运行实盘策略列表与详情',
  '2026-06-28 00:00:00',
  '2026-06-28 00:00:00',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL
WHERE NOT EXISTS (
  SELECT 1
  FROM dc.dc_modules_action
  WHERE id = 'live.strategyListView'
    AND module_id = 'live'
);

INSERT INTO dc.dc_roles_modules_action
  (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT
  'ADMIN',
  'live.strategyListView',
  'live',
  'WEB',
  NULL,
  'system',
  '管理员可查看当前运行实盘策略',
  '2026-06-28 00:00:00',
  '2026-06-28 00:00:00',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL
WHERE NOT EXISTS (
  SELECT 1
  FROM dc.dc_roles_modules_action
  WHERE role_id = 'ADMIN'
    AND action_id = 'live.strategyListView'
    AND module_id = 'live'
);

INSERT INTO dc.dc_user_role
  (user_id, role_id, user_name, role_name, close_by, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT
  'admin',
  'ADMIN',
  'admin',
  '管理员',
  'system',
  '2026-06-28 00:00:00',
  '2026-06-28 00:00:00',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL
WHERE NOT EXISTS (
  SELECT 1
  FROM dc.dc_user_role
  WHERE user_id = 'admin'
    AND role_id = 'ADMIN'
);
