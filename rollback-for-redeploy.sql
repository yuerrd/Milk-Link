-- 回退迁移版本到旧镜像支持的版本
-- 保留所有数据结构和数据，只是改变版本号让旧容器能启动

-- 将版本回退到 a2555c5f3358（初始版本）
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('a2555c5f3358');

SELECT '=== 已回退到初始版本，可以启动旧容器 ===' AS info;
SELECT * FROM alembic_version;
