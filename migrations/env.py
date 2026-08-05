# ───────────────────────────────────────────────────────────────────
# Alembic environment script
# ───────────────────────────────────────────────────────────────────
# WHAT THIS IS: the glue Alembic runs to figure out (a) what the
# "target" schema looks like (our SQLAlchemy models) and (b) what
# database to actually connect to.
#
# TWO WAYS THIS GETS INVOKED:
#   1. Programmatically, from src/database.py's run_migrations() --
#      the normal path, used on every scraper startup. That code
#      builds an alembic.config.Config and calls
#      cfg.set_main_option("sqlalchemy.url", <the real, already
#      environment-scoped URL from config.yaml/_environment_scoped_db_url>)
#      before invoking `command.upgrade(cfg, "head")`. That override
#      lands in the same [alembic] "sqlalchemy.url" key this file
#      reads below, so no extra wiring is needed here for that path.
#   2. Manually, via the bare `alembic` CLI (e.g. `alembic upgrade
#      head` from a terminal, for ops/debugging). In that case there's
#      no Config object being built by our code, so alembic.ini's own
#      sqlalchemy.url (see that file) is what's used -- it defaults to
#      the production DB path, matching config.yaml.
#
# WHY target_metadata IS SET: without it, `alembic revision
# --autogenerate` can't compare the models against the database to
# propose a migration. This repo's models live under src/ (src-layout,
# same PYTHONPATH=src convention used everywhere else -- see
# Dockerfile, README Quick Start), so that directory is added to
# sys.path here before importing them.
# ───────────────────────────────────────────────────────────────────
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Make src/ importable (mirrors PYTHONPATH=src used everywhere else
# in this project -- see Dockerfile, README, tests/*.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from database import Base  # noqa: E402 -- must follow the sys.path insert above

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Our models' metadata -- lets `alembic revision --autogenerate`
# diff the database against the ORM models defined in
# src/database.py.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
