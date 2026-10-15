import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import PasswordField from './PasswordField';

afterEach(cleanup);

test('password visibility is independent, preserves input, and never submits the form', () => {
  const submit = vi.fn((event) => event.preventDefault());
  render(<form onSubmit={submit}>
    <PasswordField defaultValue="secret" required minLength={6} maxLength={128} autoComplete="current-password" />
    <PasswordField label="New password" />
  </form>);
  const input = screen.getByLabelText('Password') as HTMLInputElement;
  expect(input.type).toBe('password');
  fireEvent.click(screen.getByRole('button', { name: 'Show password' }));
  expect(input.type).toBe('text');
  expect(input.value).toBe('secret');
  expect((screen.getByLabelText('New password') as HTMLInputElement).type).toBe('password');
  expect(screen.getByRole('button', { name: 'Hide password' }).getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: 'Hide password' }));
  expect(input.type).toBe('password');
  expect(input.minLength).toBe(6);
  expect(input.maxLength).toBe(128);
  expect(input.autocomplete).toBe('current-password');
  expect(submit).not.toHaveBeenCalled();
});
