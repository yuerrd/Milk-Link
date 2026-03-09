-- 将数据库版本直接设为最终版本
-- 因为字段已经通过 manual-upgrade.sql 全部添加完成

DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('360b08025977');

SELECT '=== 已设置为最终版本，容器启动时将跳过迁移 ===' AS info;
SELECT * FROM alembic_version;
