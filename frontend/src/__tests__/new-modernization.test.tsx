import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { NewModernization } from '../pages/NewModernization';

/**
 * The normal product flow is ZIP-only: COBOL archive in, modernization out.
 * Java candidate upload stays an internal/test-only backend path and Git
 * ingestion does not exist yet — neither may appear in the UI.
 */
describe('NewModernization product flow', () => {
  it('offers a ZIP source archive and no Java candidate upload', () => {
    render(<NewModernization onSubmit={() => {}} />);

    expect(screen.getByText('Source Archive')).toBeInTheDocument();
    expect(
      screen.getByText(/Upload a ZIP archive containing your legacy application source/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/java candidate/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/candidate upload/i)).not.toBeInTheDocument();
  });

  it('offers no Git import until backend Git ingestion exists', () => {
    render(<NewModernization onSubmit={() => {}} />);

    expect(screen.queryByText(/git repository/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/clone|repository url/i)).not.toBeInTheDocument();
  });

  it('auto-detects the application name from the ZIP filename', () => {
    render(<NewModernization onSubmit={() => {}} />);

    const dropzones = screen.getAllByText(/drop|browse|select/i);
    expect(dropzones.length).toBeGreaterThan(0);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).not.toBeNull();
    expect(fileInput.getAttribute('accept')).toContain('.zip');

    const zip = new File(['pk'], 'payroll-nightly.zip', { type: 'application/zip' });
    fireEvent.change(fileInput, { target: { files: [zip] } });

    expect(screen.getByText('Detected from uploaded archive')).toBeInTheDocument();
  });

  it('starts modernization with name, workload and ZIP only', () => {
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const zip = new File(['pk'], 'claims.zip', { type: 'application/zip' });
    fireEvent.change(fileInput, { target: { files: [zip] } });

    fireEvent.click(screen.getByText(/Start Modernization/));

    expect(onSubmit).toHaveBeenCalledOnce();
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.zipFile).toBe(zip);
    expect(payload.name).toBeTruthy();
    expect(payload.workloadId).toBeTruthy();
    expect(payload).not.toHaveProperty('candidate');
    expect(payload).not.toHaveProperty('gitUrl');
  });
});
