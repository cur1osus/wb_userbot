.PHONY: build
build:
	uv run -m bot


.PHONY: sync_models
sync_models:
	cp ../wb_userbot/bot/db/models.py ../wb_managerbot/bot/db/models.py
