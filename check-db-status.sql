-- 检查数据库当前状态

-- 1. 检查迁移版本
SELECT '=== 当前迁移版本 ===' AS info;
SELECT * FROM alembic_version;

-- 2. 检查表结构
SELECT '=== feeding_records 表结构 ===' AS info;
DESCRIBE feeding_records;

-- 3. 检查是否有数据
SELECT '=== 记录总数 ===' AS info;
SELECT COUNT(*) as total_records FROM feeding_records;

-- 4. 检查最近一条记录的字段
SELECT '=== 最近一条记录 ===' AS info;
SELECT * FROM feeding_records ORDER BY fed_at DESC LIMIT 1;
