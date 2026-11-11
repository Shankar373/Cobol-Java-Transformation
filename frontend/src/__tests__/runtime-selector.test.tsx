import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import React from 'react';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, getRuntimes: vi.fn() };
});

import { NewModernization } from '../pages/NewModernization';
import * as api from '../api/client';

const optionsOf = (): string[] =>
  Array.from(
    (screen.getByLabelText('Target runtime') as HTMLSelectElement).options,
  ).map((o) => o.value);

beforeEach(() => {
  vi.clearAllMocks();
});

// Roadmap unit 1: the server's runtime registry decides what can be chosen.
describe('target runtime selector', () => {
  it('offers only the runtimes the server marks certified', async () => {
    vi.mocked(api.getRuntimes).mockResolvedValue([
      { key: 'spring_boot', label: 'Spring Boot', certified: true, note: 'certified' },
      { key: 'jakarta_ee', label: 'Jakarta EE (generation profile)', certified: false, note: 'not certified' },
      { key: 'quarkus', label: 'Quarkus (command mode)', certified: true, note: 'command mode' },
    ]);
    render(<NewModernization onSubmit={vi.fn()} />);
    await waitFor(() => expect(optionsOf()).toEqual(['', 'spring_boot', 'quarkus']));
    expect(screen.queryByText(/Jakarta/)).toBeNull();
  });

  it('keeps the built-in certified list when the server cannot be reached', async () => {
    vi.mocked(api.getRuntimes).mockRejectedValue(new api.ApiError(503, 'down'));
    render(<NewModernization onSubmit={vi.fn()} />);
    await waitFor(() => expect(api.getRuntimes).toHaveBeenCalled());
    expect(optionsOf()).toEqual(['', 'spring_boot', 'plain_java', 'quarkus', 'micronaut']);
  });

  it('has no default: nothing is selected until the user chooses, even with one certified runtime', async () => {
    vi.mocked(api.getRuntimes).mockResolvedValue([
      { key: 'quarkus', label: 'Quarkus', certified: true, note: '' },
    ]);
    render(<NewModernization onSubmit={vi.fn()} />);
    await waitFor(() => expect(optionsOf()).toEqual(['', 'quarkus']));
    const select = screen.getByLabelText('Target runtime') as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(select.required).toBe(true);
    expect((select.options[0] as HTMLOptionElement).disabled).toBe(true);
  });

  it('clears, never replaces, a choice the server stops offering', async () => {
    vi.mocked(api.getRuntimes).mockResolvedValue([
      { key: 'quarkus', label: 'Quarkus', certified: true, note: '' },
    ]);
    render(<NewModernization onSubmit={vi.fn()} />);
    const select = screen.getByLabelText('Target runtime') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'spring_boot' } });
    await waitFor(() => expect(api.getRuntimes).toHaveBeenCalled());
    await waitFor(() => expect(select.value).toBe(''));
  });
});
