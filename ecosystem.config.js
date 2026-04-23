// PM2 Ecosystem Configuration — Autonomous Content Bridge
module.exports = {
  apps: [
    {
      name: 'content-bridge-api',
      cwd: '/opt/content-bridge',
      script: '/opt/content-bridge/venv/bin/uvicorn',
      args: 'backend.main:app --host 0.0.0.0 --port 8000 --workers 2',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/opt/content-bridge',
      },
      watch: false,
      max_memory_restart: '1G',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: '/opt/content-bridge/data/logs/api-error.log',
      out_file: '/opt/content-bridge/data/logs/api-out.log',
      merge_logs: true,
    },
    {
      name: 'content-bridge-frontend',
      cwd: '/opt/content-bridge/frontend',
      script: 'npm',
      args: 'start',
      interpreter: 'none',
      env: {
        PORT: 3000,
        NODE_ENV: 'production',
      },
      watch: false,
      max_memory_restart: '512M',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: '/opt/content-bridge/data/logs/frontend-error.log',
      out_file: '/opt/content-bridge/data/logs/frontend-out.log',
      merge_logs: true,
    },
  ],
};
