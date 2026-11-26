import js from '@eslint/js';
import babelParser from '@babel/eslint-parser';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  {
    ignores: ['dist/**', 'node_modules/**', 'data/**', 'python_core/**', 'apps/**', 'tools/**', 'tests/**', 'tests_phases/**', 'scripts/**', 'infra/**', 'phases/**'],
  },
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        ecmaVersion: 'latest',
        sourceType: 'module',
        babelOptions: {
          presets: ['@babel/preset-typescript', ['@babel/preset-react', { runtime: 'automatic' }]],
        },
      },
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'no-undef': 'off',
      'no-unused-vars': 'off',
    },
  },
];
