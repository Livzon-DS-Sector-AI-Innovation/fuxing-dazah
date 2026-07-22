# 启动基础服务（db + redis），开发时只需这个
up:
	docker compose up -d

# 启动全部服务包含 app
up-app:
	docker compose --profile app up -d

# 停止所有服务（数据不会丢失）
down:
	docker compose down

# 查看服务状态
ps:
	docker compose ps

# 查看日志
logs:
	docker compose logs -f

# 彻底清除数据（谨慎！）
clean:
	docker compose down -v