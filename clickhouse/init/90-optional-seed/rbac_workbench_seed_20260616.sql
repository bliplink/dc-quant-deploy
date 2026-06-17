-- Workbench RBAC manual seed for ClickHouse
-- Password for all seeded users: Gjk_123456

INSERT INTO dc.dc_roles (id, role_name, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', '管理员', 'WEB', NULL, 'system', '全部页面与全部动作权限', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles WHERE id = 'ADMIN');
INSERT INTO dc.dc_roles (id, role_name, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'STRATEGY', '策略研究员', 'WEB', NULL, 'system', '策略生成、回测、策略优化', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles WHERE id = 'STRATEGY');
INSERT INTO dc.dc_roles (id, role_name, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'LIVE', '实盘操作员', 'WEB', NULL, 'system', '实盘运行与日末复盘', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles WHERE id = 'LIVE');
INSERT INTO dc.dc_roles (id, role_name, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'OBSERVER', '系统观察员', 'WEB', NULL, 'system', '系统状态只读查看', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles WHERE id = 'OBSERVER');

INSERT INTO dc.dc_modules (id, module_name, parent_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'generate', '策略生成', '0', 'WEB', NULL, 'system', '策略生成页面', '2026-06-16 00:00:00', '2026-06-16 00:00:00', '10', NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules WHERE id = 'generate');
INSERT INTO dc.dc_modules (id, module_name, parent_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'backtest', '回测验证', '0', 'WEB', NULL, 'system', '回测验证页面', '2026-06-16 00:00:00', '2026-06-16 00:00:00', '20', NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules WHERE id = 'backtest');
INSERT INTO dc.dc_modules (id, module_name, parent_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'live', '实盘运行', '0', 'WEB', NULL, 'system', '当前运行实盘策略页面', '2026-06-16 00:00:00', '2026-06-16 00:00:00', '30', NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules WHERE id = 'live');
INSERT INTO dc.dc_modules (id, module_name, parent_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'review', '日末复盘', '0', 'WEB', NULL, 'system', '日末复盘页面', '2026-06-16 00:00:00', '2026-06-16 00:00:00', '40', NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules WHERE id = 'review');
INSERT INTO dc.dc_modules (id, module_name, parent_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'system', '系统状态', '0', 'WEB', NULL, 'system', '系统状态页面', '2026-06-16 00:00:00', '2026-06-16 00:00:00', '50', NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules WHERE id = 'system');
INSERT INTO dc.dc_modules (id, module_name, parent_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'workflow', '策略优化', '0', 'WEB', NULL, 'system', '策略优化工作台页面', '2026-06-16 00:00:00', '2026-06-16 00:00:00', '60', NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules WHERE id = 'workflow');

INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'generate.create', '生成策略', 'generate', 'WEB', NULL, 'system', '单次发起策略生成', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'generate.create' AND module_id = 'generate');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'generate.batchCreate', '批量生成并回测', 'generate', 'WEB', NULL, 'system', '批量生成策略并提交回测', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'generate.batchCreate' AND module_id = 'generate');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'backtest.create', '创建回测任务', 'backtest', 'WEB', NULL, 'system', '创建单个回测任务', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'backtest.create' AND module_id = 'backtest');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'workflow.rerun', '重跑工作流', 'workflow', 'WEB', NULL, 'system', '重跑单个策略工作流', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'workflow.rerun' AND module_id = 'workflow');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'workflow.batchRerun', '批量重跑工作流', 'workflow', 'WEB', NULL, 'system', '批量重跑失败工作流', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'workflow.batchRerun' AND module_id = 'workflow');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'live.online', '上线实盘策略', 'live', 'WEB', NULL, 'system', '手工上线实盘策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'live.online' AND module_id = 'live');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'live.offline', '下线实盘策略', 'live', 'WEB', NULL, 'system', '手工下线实盘策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'live.offline' AND module_id = 'live');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'live.gapFill', '一键补充缺少场景', 'live', 'WEB', NULL, 'system', '一键补齐缺少场景策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'live.gapFill' AND module_id = 'live');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'live.batchDeleteOffline', '批量删除已下线策略', 'live', 'WEB', NULL, 'system', '批量删除当前页已下线策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'live.batchDeleteOffline' AND module_id = 'live');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'system.configSave', '保存系统参数', 'system', 'WEB', NULL, 'system', '保存系统参数配置', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'system.configSave' AND module_id = 'system');
INSERT INTO dc.dc_modules_action (id, action_name, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'system.configTest', '测试系统参数', 'system', 'WEB', NULL, 'system', '测试系统参数配置', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_modules_action WHERE id = 'system.configTest' AND module_id = 'system');

INSERT INTO dc.dc_users (user_id, user_name, name, password, mail, user_type, enable, remark, create_time, update_time, mac, mac1, mac2, inf1, inf2, inf3, inf4, inf5, enable_trade, enable_cash_in, enable_cash_out, referrer, close_by, location)
SELECT 'admin', 'admin', '管理员', '680a07eec62f17f8e46fa64502fe7764dfdb7b8a9174a65be199e5a8785396d8', NULL, '6', '1', '管理员角色默认用户', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '1', '1', '1', '', 'system', '0'
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_users WHERE user_name = 'admin');
INSERT INTO dc.dc_users (user_id, user_name, name, password, mail, user_type, enable, remark, create_time, update_time, mac, mac1, mac2, inf1, inf2, inf3, inf4, inf5, enable_trade, enable_cash_in, enable_cash_out, referrer, close_by, location)
SELECT 'strategy_user', 'strategy_user', '策略研究员', '680a07eec62f17f8e46fa64502fe7764dfdb7b8a9174a65be199e5a8785396d8', NULL, '6', '1', '策略研究角色默认用户', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '1', '1', '1', '', 'system', '0'
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_users WHERE user_name = 'strategy_user');
INSERT INTO dc.dc_users (user_id, user_name, name, password, mail, user_type, enable, remark, create_time, update_time, mac, mac1, mac2, inf1, inf2, inf3, inf4, inf5, enable_trade, enable_cash_in, enable_cash_out, referrer, close_by, location)
SELECT 'live_user', 'live_user', '实盘操作员', '680a07eec62f17f8e46fa64502fe7764dfdb7b8a9174a65be199e5a8785396d8', NULL, '6', '1', '实盘操作角色默认用户', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '1', '1', '1', '', 'system', '0'
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_users WHERE user_name = 'live_user');
INSERT INTO dc.dc_users (user_id, user_name, name, password, mail, user_type, enable, remark, create_time, update_time, mac, mac1, mac2, inf1, inf2, inf3, inf4, inf5, enable_trade, enable_cash_in, enable_cash_out, referrer, close_by, location)
SELECT 'observer_user', 'observer_user', '系统观察员', '680a07eec62f17f8e46fa64502fe7764dfdb7b8a9174a65be199e5a8785396d8', NULL, '6', '1', '系统观察角色默认用户', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '1', '1', '1', '', 'system', '0'
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_users WHERE user_name = 'observer_user');

INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'generate', 'WEB', NULL, 'system', '管理员可访问策略生成', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'ADMIN' AND module_id = 'generate');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'backtest', 'WEB', NULL, 'system', '管理员可访问回测验证', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'ADMIN' AND module_id = 'backtest');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'live', 'WEB', NULL, 'system', '管理员可访问实盘运行', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'ADMIN' AND module_id = 'live');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'review', 'WEB', NULL, 'system', '管理员可访问日末复盘', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'ADMIN' AND module_id = 'review');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'system', 'WEB', NULL, 'system', '管理员可访问系统状态', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'ADMIN' AND module_id = 'system');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'workflow', 'WEB', NULL, 'system', '管理员可访问策略优化', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'ADMIN' AND module_id = 'workflow');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'STRATEGY', 'generate', 'WEB', NULL, 'system', '策略研究员可访问策略生成', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'STRATEGY' AND module_id = 'generate');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'STRATEGY', 'backtest', 'WEB', NULL, 'system', '策略研究员可访问回测验证', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'STRATEGY' AND module_id = 'backtest');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'STRATEGY', 'workflow', 'WEB', NULL, 'system', '策略研究员可访问策略优化', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'STRATEGY' AND module_id = 'workflow');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'LIVE', 'live', 'WEB', NULL, 'system', '实盘操作员可访问实盘运行', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'LIVE' AND module_id = 'live');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'LIVE', 'review', 'WEB', NULL, 'system', '实盘操作员可访问日末复盘', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'LIVE' AND module_id = 'review');
INSERT INTO dc.dc_roles_modules (role_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'OBSERVER', 'system', 'WEB', NULL, 'system', '系统观察员可访问系统状态', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules WHERE role_id = 'OBSERVER' AND module_id = 'system');

INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'generate.create', 'generate', 'WEB', NULL, 'system', '管理员可执行生成策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'generate.create' AND module_id = 'generate');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'generate.batchCreate', 'generate', 'WEB', NULL, 'system', '管理员可批量生成并回测', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'generate.batchCreate' AND module_id = 'generate');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'backtest.create', 'backtest', 'WEB', NULL, 'system', '管理员可创建回测任务', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'backtest.create' AND module_id = 'backtest');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'workflow.rerun', 'workflow', 'WEB', NULL, 'system', '管理员可重跑工作流', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'workflow.rerun' AND module_id = 'workflow');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'workflow.batchRerun', 'workflow', 'WEB', NULL, 'system', '管理员可批量重跑工作流', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'workflow.batchRerun' AND module_id = 'workflow');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'live.online', 'live', 'WEB', NULL, 'system', '管理员可上线实盘策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'live.online' AND module_id = 'live');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'live.offline', 'live', 'WEB', NULL, 'system', '管理员可下线实盘策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'live.offline' AND module_id = 'live');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'live.gapFill', 'live', 'WEB', NULL, 'system', '管理员可一键补充缺少场景', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'live.gapFill' AND module_id = 'live');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'live.batchDeleteOffline', 'live', 'WEB', NULL, 'system', '管理员可批量删除已下线策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'live.batchDeleteOffline' AND module_id = 'live');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'system.configSave', 'system', 'WEB', NULL, 'system', '管理员可保存系统参数', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'system.configSave' AND module_id = 'system');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'ADMIN', 'system.configTest', 'system', 'WEB', NULL, 'system', '管理员可测试系统参数', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'ADMIN' AND action_id = 'system.configTest' AND module_id = 'system');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'STRATEGY', 'generate.create', 'generate', 'WEB', NULL, 'system', '策略研究员可执行生成策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'STRATEGY' AND action_id = 'generate.create' AND module_id = 'generate');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'STRATEGY', 'backtest.create', 'backtest', 'WEB', NULL, 'system', '策略研究员可创建回测任务', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'STRATEGY' AND action_id = 'backtest.create' AND module_id = 'backtest');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'STRATEGY', 'workflow.rerun', 'workflow', 'WEB', NULL, 'system', '策略研究员可重跑单个工作流', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'STRATEGY' AND action_id = 'workflow.rerun' AND module_id = 'workflow');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'LIVE', 'live.online', 'live', 'WEB', NULL, 'system', '实盘操作员可上线实盘策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'LIVE' AND action_id = 'live.online' AND module_id = 'live');
INSERT INTO dc.dc_roles_modules_action (role_id, action_id, module_id, terminal, ip, close_by, remark, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'LIVE', 'live.offline', 'live', 'WEB', NULL, 'system', '实盘操作员可下线实盘策略', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_roles_modules_action WHERE role_id = 'LIVE' AND action_id = 'live.offline' AND module_id = 'live');

INSERT INTO dc.dc_user_role (user_id, role_id, user_name, role_name, close_by, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'admin', 'ADMIN', 'admin', '管理员', 'system', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_user_role WHERE user_id = 'admin' AND role_id = 'ADMIN');
INSERT INTO dc.dc_user_role (user_id, role_id, user_name, role_name, close_by, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'strategy_user', 'STRATEGY', 'strategy_user', '策略研究员', 'system', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_user_role WHERE user_id = 'strategy_user' AND role_id = 'STRATEGY');
INSERT INTO dc.dc_user_role (user_id, role_id, user_name, role_name, close_by, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'live_user', 'LIVE', 'live_user', '实盘操作员', 'system', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_user_role WHERE user_id = 'live_user' AND role_id = 'LIVE');
INSERT INTO dc.dc_user_role (user_id, role_id, user_name, role_name, close_by, create_time, update_time, inf1, inf2, inf3, inf4, inf5)
SELECT 'observer_user', 'OBSERVER', 'observer_user', '系统观察员', 'system', '2026-06-16 00:00:00', '2026-06-16 00:00:00', NULL, NULL, NULL, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM dc.dc_user_role WHERE user_id = 'observer_user' AND role_id = 'OBSERVER');
