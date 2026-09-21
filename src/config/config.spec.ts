import { configuration } from './configuration.js';
import { validateEnv } from './env.validation.js';

describe('validateEnv', () => {
  it('accepts an empty environment (every variable has a default)', () => {
    expect(() => validateEnv({})).not.toThrow();
  });

  it('passes undeclared variables straight through', () => {
    const env = { PATH: '/usr/bin', PORT: '3005' };
    expect(validateEnv(env)).toBe(env);
  });

  it('rejects a non-numeric port', () => {
    expect(() => validateEnv({ PORT: 'not-a-port' })).toThrow(
      /Invalid environment configuration/,
    );
  });

  it('rejects a port outside the valid range', () => {
    expect(() => validateEnv({ POSTGRES_PORT: '99999' })).toThrow(
      /POSTGRES_PORT/,
    );
  });

  it('rejects an unknown NODE_ENV', () => {
    expect(() => validateEnv({ NODE_ENV: 'staging' })).toThrow(/NODE_ENV/);
  });

  it('accepts both spellings of the boolean flags', () => {
    expect(() =>
      validateEnv({ POSTGRES_SYNC: 'false', POSTGRES_LOGGING: '1' }),
    ).not.toThrow();
  });

  it('rejects a boolean flag that is neither true nor false', () => {
    expect(() => validateEnv({ POSTGRES_SYNC: 'maybe' })).toThrow(
      /POSTGRES_SYNC/,
    );
  });

  it('rejects a URL without a protocol', () => {
    expect(() => validateEnv({ OWUI_URL: 'localhost:8080' })).toThrow(
      /OWUI_URL/,
    );
  });
});

describe('configuration', () => {
  const original = { ...process.env };

  afterEach(() => {
    process.env = { ...original };
  });

  it('coerces numeric variables to numbers', () => {
    process.env.PORT = '3005';
    process.env.POSTGRES_PORT = '5433';

    const config = configuration();
    expect(config.port).toBe(3005);
    expect(config.database.port).toBe(5433);
  });

  it('reads POSTGRES_SYNC=false as false rather than a truthy string', () => {
    process.env.POSTGRES_SYNC = 'false';
    expect(configuration().database.synchronize).toBe(false);
  });

  it('defaults synchronize to true when unset', () => {
    delete process.env.POSTGRES_SYNC;
    expect(configuration().database.synchronize).toBe(true);
  });

  it('strips trailing slashes from the Open WebUI URL', () => {
    process.env.OWUI_URL = 'http://localhost:8080//';
    expect(configuration().owui.url).toBe('http://localhost:8080');
  });

  it('treats a blank API key as absent', () => {
    process.env.OWUI_API_KEY = '   ';
    expect(configuration().owui.apiKey).toBeUndefined();
  });

  it('derives the raw and ready directories from UPLOADS_DIR', () => {
    process.env.UPLOADS_DIR = '/srv/turizm-uploads';

    const { uploads } = configuration();
    expect(uploads.rawDir).toBe('/srv/turizm-uploads/raw');
    expect(uploads.readyDir).toBe('/srv/turizm-uploads/ready');
  });

  it('turns MAX_UPLOAD_MB into bytes', () => {
    process.env.MAX_UPLOAD_MB = '50';
    expect(configuration().uploads.maxBytes).toBe(50 * 1024 * 1024);
  });
});
