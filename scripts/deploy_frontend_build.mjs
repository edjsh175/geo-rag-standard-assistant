import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, '..');
const frontendDir = path.join(root, 'frontend');
const distDir = path.join(frontendDir, 'dist');
const buildMetaPath = path.join(distDir, 'build-meta.json');
const npmExecutable = process.platform === 'win32' ? 'npm.cmd' : 'npm';

function parseArgs(argv) {
  const options = {
    allowDirty: false,
    expectedCommit: undefined,
    npmInstall: 'ci',
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];

    if (value === '--allow-dirty') {
      options.allowDirty = true;
      continue;
    }

    if (value === '--expected-commit') {
      options.expectedCommit = argv[index + 1];
      index += 1;
      continue;
    }

    if (value === '--npm-install') {
      options.npmInstall = argv[index + 1];
      index += 1;
      continue;
    }

    if (value === '--help' || value === '-h') {
      printHelp();
      process.exit(0);
    }

    throw new Error(`Unknown argument: ${value}`);
  }

  if (!['ci', 'install', 'skip'].includes(options.npmInstall)) {
    throw new Error(`Unsupported --npm-install value: ${options.npmInstall}`);
  }

  return options;
}

function printHelp() {
  console.log(`Usage:
  node scripts/deploy_frontend_build.mjs [options]

Options:
  --expected-commit <sha>  Require git HEAD to match this commit before build
  --allow-dirty            Allow building from a dirty worktree
  --npm-install <mode>     One of: ci, install, skip
`);
}

function commandOutput(command, args, cwd) {
  return execFileSync(command, args, {
    cwd,
    encoding: 'utf-8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

function run(command, args, cwd) {
  execFileSync(command, args, {
    cwd,
    stdio: 'inherit',
  });
}

function validateGitState(expectedCommit, allowDirty) {
  const headCommit = commandOutput('git', ['rev-parse', 'HEAD'], root);
  const dirty = commandOutput('git', ['status', '--short'], root).length > 0;

  if (expectedCommit && headCommit !== expectedCommit) {
    throw new Error(
      `Refusing to build frontend from the wrong source revision.\nExpected commit: ${expectedCommit}\nCurrent HEAD:    ${headCommit}`
    );
  }

  if (dirty && !allowDirty) {
    throw new Error(
      'Refusing to build frontend from a dirty worktree.\nCommit or stash local changes first, or rerun with --allow-dirty if this is intentional.'
    );
  }

  return {headCommit, dirty};
}

function installDependencies(mode) {
  if (mode === 'skip') {
    return;
  }

  if (mode === 'ci') {
    run(npmExecutable, ['ci'], frontendDir);
    return;
  }

  run(npmExecutable, ['install'], frontendDir);
}

function writeBuildMeta(headCommit, dirty, expectedCommit) {
  fs.mkdirSync(distDir, {recursive: true});
  const payload = {
    git_commit: headCommit,
    git_commit_short: headCommit.slice(0, 7),
    expected_commit: expectedCommit ?? null,
    git_dirty: dirty,
    built_at_utc: new Date().toISOString(),
    builder_hostname: os.hostname(),
  };
  fs.writeFileSync(buildMetaPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8');
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const {headCommit, dirty} = validateGitState(options.expectedCommit, options.allowDirty);
  installDependencies(options.npmInstall);
  run(npmExecutable, ['run', 'build'], frontendDir);
  writeBuildMeta(headCommit, dirty, options.expectedCommit);

  console.log('Frontend build completed.');
  console.log(`Commit: ${headCommit}`);
  console.log(`Build metadata: ${buildMetaPath}`);
}

main();
