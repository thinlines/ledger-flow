import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Static guard for ADR-0001 (solid surfaces — no `backdrop-filter`).
 *
 * Scans every non-test source file under the frontend `src/` tree and fails
 * if it finds `backdrop-filter` or `backdrop-blur-*`. The shell stacks
 * sticky surfaces on every route, and each blurred surface forces the
 * compositor to re-sample its backdrop on every scroll frame — the cause
 * of the app-wide scroll jank fixed by removing the five original sites.
 * If a future surface genuinely needs blur, it must come with a profiled
 * scroll trace showing it does not regress frame rate (see ADR-0001).
 */

const SRC_ROOT = fileURLToPath(new URL('../', import.meta.url));

const SCANNED_EXTENSIONS = ['.svelte', '.ts', '.tsx', '.js', '.jsx', '.css', '.scss', '.html'];

// Test files are excluded so the guard itself can name the forbidden tokens.
function isTestFile(path: string): boolean {
  return /\.test\.[cm]?[jt]sx?$/.test(path);
}

function shouldScan(path: string): boolean {
  if (isTestFile(path)) return false;
  return SCANNED_EXTENSIONS.some((ext) => path.endsWith(ext));
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      walk(full, out);
    } else if (stat.isFile() && shouldScan(full)) {
      out.push(full);
    }
  }
  return out;
}

const FORBIDDEN = [/backdrop-filter/, /backdrop-blur(?:-[a-z0-9]+)?/];

describe('frontend source guard — ADR-0001 (no backdrop-filter)', () => {
  it('contains no backdrop-filter / backdrop-blur-* anywhere under src/', () => {
    const offenders: string[] = [];
    for (const file of walk(SRC_ROOT)) {
      const text = readFileSync(file, 'utf-8');
      const lines = text.split('\n');
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        for (const pattern of FORBIDDEN) {
          if (pattern.test(line)) {
            offenders.push(`${relative(SRC_ROOT, file)}:${i + 1}: ${line.trim()}`);
            break;
          }
        }
      }
    }
    expect(
      offenders,
      `Found forbidden backdrop-filter / backdrop-blur usage:\n${offenders.join('\n')}`
    ).toEqual([]);
  });
});
