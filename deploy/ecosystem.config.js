/**
 * PM2 process definition for the Django backend.
 *
 * PM2 does not run Python itself — it supervises the gunicorn binary from the
 * project's virtualenv, which is why `interpreter` is "none".
 *
 *   pm2 start deploy/ecosystem.config.js
 *   pm2 save
 *
 * Adjust APP_DIR below if the checkout lives somewhere else.
 */

const APP_DIR = "/var/www/ai-agent-turizm-back";

module.exports = {
  apps: [
    {
      name: "turizm-back",
      cwd: APP_DIR,
      script: `${APP_DIR}/.venv/bin/gunicorn`,
      interpreter: "none",

      // IMPORTANT — exactly one worker, in fork mode.
      //
      // The ingestion pipeline keeps its queue and its "currently converting"
      // registry inside the process (apps/pipeline/runner.py). A second worker
      // would have its own copy of both, so the same material could be
      // converted twice and the two runs would overwrite each other's status
      // and Open WebUI file ids. Concurrency comes from threads instead.
      instances: 1,
      exec_mode: "fork",

      args: [
        "config.wsgi:application",
        "--bind", "127.0.0.1:3005",
        "--workers", "1",
        "--threads", "8",
        // A 200 MB upload over a slow link must not be killed mid-request.
        "--timeout", "300",
        // Give in-flight conversions a chance to finish on reload.
        "--graceful-timeout", "60",
        "--access-logfile", "-",
        "--error-logfile", "-",
        // Deliberately NO --max-requests: recycling the worker would kill the
        // background conversion threads along with it.
      ].join(" "),

      env: {
        DJANGO_SETTINGS_MODULE: "config.settings",
        // Everything else is read from APP_DIR/.env by django-environ.
        PYTHONUNBUFFERED: "1",
      },

      autorestart: true,
      max_restarts: 10,
      min_uptime: "20s",
      // Conversions hold memory while parsing; restart if something leaks.
      max_memory_restart: "1G",
      kill_timeout: 65000,

      merge_logs: true,
      time: true,
      out_file: `${APP_DIR}/logs/out.log`,
      error_file: `${APP_DIR}/logs/error.log`,

      // Source files are deployed by git; watching them would restart the app
      // mid-conversion every time a file's mtime changed.
      watch: false,
    },
  ],
};
