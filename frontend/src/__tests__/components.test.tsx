import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { Header } from '../components/Header';
import { PageContainer } from '../components/PageContainer';
import { StatCard } from '../components/StatCard';
import { SectionCard } from '../components/SectionCard';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { EmptyState } from '../components/EmptyState';
import { StageIndicator } from '../components/StageIndicator';
import { FileUpload } from '../components/FileUpload';

describe('Header', () => {
  it('renders brand name', () => {
    render(<Header />);
    expect(screen.getByText('COBOL \u2192 Java')).toBeInTheDocument();
  });

  it('renders navigation links', () => {
    render(<Header />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('New Modernization')).toBeInTheDocument();
  });

  it('calls onNavigate when nav link clicked', () => {
    const onNav = vi.fn();
    render(<Header onNavigate={onNav} />);
    fireEvent.click(screen.getByText('Dashboard'));
    expect(onNav).toHaveBeenCalledWith('dashboard');
  });
});

describe('PageContainer', () => {
  it('renders title and children', () => {
    render(
      <PageContainer title="Test Title">
        <div>child content</div>
      </PageContainer>
    );
    expect(screen.getByText('Test Title')).toBeInTheDocument();
    expect(screen.getByText('child content')).toBeInTheDocument();
  });

  it('renders subtitle when provided', () => {
    render(
      <PageContainer title="T" subtitle="My subtitle"><div /></PageContainer>
    );
    expect(screen.getByText('My subtitle')).toBeInTheDocument();
  });
});

describe('StatCard', () => {
  it('renders value and label', () => {
    render(<StatCard icon="?" value={42} label="Items" />);
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('Items')).toBeInTheDocument();
  });
});

describe('SectionCard', () => {
  it('renders title with count', () => {
    render(
      <SectionCard title="Recipes" count={5}>
        <div>content</div>
      </SectionCard>
    );
    expect(screen.getByText(/Recipes \(5\)/)).toBeInTheDocument();
    expect(screen.getByText('content')).toBeInTheDocument();
  });
});

describe('Badge', () => {
  it('renders with default variant', () => {
    render(<Badge>Active</Badge>);
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('renders success variant', () => {
    render(<Badge variant="success">PASS</Badge>);
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  it('renders sm size', () => {
    render(<Badge size="sm">Small</Badge>);
    expect(screen.getByText('Small')).toBeInTheDocument();
  });
});

describe('Button', () => {
  it('renders children text', () => {
    render(<Button>Click Me</Button>);
    expect(screen.getByText('Click Me')).toBeInTheDocument();
  });

  it('calls onClick when clicked', () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    fireEvent.click(screen.getByText('Go'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('can be disabled', () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByText('Disabled')).toBeDisabled();
  });
});

describe('EmptyState', () => {
  it('renders title and description', () => {
    render(
      <EmptyState title="Nothing here" description="No items yet" />
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
    expect(screen.getByText('No items yet')).toBeInTheDocument();
  });
});

describe('StageIndicator', () => {
  it('renders all stages', () => {
    render(<StageIndicator current="VALIDATING_EVIDENCE" />);
    expect(screen.getByText('CREATED')).toBeInTheDocument();
    expect(screen.getByText('TRANSFORMING')).toBeInTheDocument();
    expect(screen.getByText('VALIDATING_EVIDENCE')).toBeInTheDocument();
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
  });

  it('includes DISCOVERY_COMPLETED as its own step', () => {
    render(<StageIndicator current="DISCOVERING" />);
    expect(screen.getByText('DISCOVERY_COMPLETED')).toBeInTheDocument();
  });

  it('does not render INGESTING as a run stage', () => {
    render(<StageIndicator current="DISCOVERING" />);
    expect(screen.queryByText('INGESTING')).not.toBeInTheDocument();
  });

  it('orders EXECUTING_ORACLE before BUILDING (backend order)', () => {
    const { container } = render(<StageIndicator current="DISCOVERING" />);
    const text = container.textContent ?? '';
    expect(text.indexOf('EXECUTING_ORACLE')).toBeLessThan(text.indexOf('BUILDING'));
  });

  it('shows error message when failed', () => {
    render(<StageIndicator current="FAILED" error="Compile error" />);
    expect(screen.getByText('Compile error')).toBeInTheDocument();
  });
});

describe('FileUpload', () => {
  it('renders drop zone text', () => {
    render(<FileUpload onFiles={() => {}} />);
    expect(screen.getByText(/Drop your ZIP archive/)).toBeInTheDocument();
    expect(screen.getByText(/click to browse/)).toBeInTheDocument();
  });

  it('has accessible button role', () => {
    render(<FileUpload onFiles={() => {}} />);
    const dropzone = screen.getByRole('button', { name: /Upload file/i });
    expect(dropzone).toBeInTheDocument();
  });

  it('renders custom label', () => {
    render(<FileUpload onFiles={() => {}} label="Upload COBOL archive" />);
    const dropzone = screen.getByRole('button', { name: /Upload COBOL archive/i });
    expect(dropzone).toBeInTheDocument();
  });
});

describe('No Java candidate upload in UI', () => {
  it('NewModernization does not show Java candidate controls', async () => {
    const { NewModernization } = await import('../pages/NewModernization');
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    // Should NOT find any Java-related upload controls
    expect(screen.queryByText(/java candidate/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Upload Java/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\.java/i)).not.toBeInTheDocument();
  });
});

describe('NewModernization auto-fill from ZIP', () => {
  it('auto-fills name from ZIP filename on selection', async () => {
    const { NewModernization } = await import('../pages/NewModernization');
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    const file = new File(['content'], 'payroll-system.zip', { type: 'application/zip' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await vi.waitFor(() => {
      expect(screen.getByDisplayValue('payroll-system')).toBeInTheDocument();
    });
  });

  it('normalizes filename with spaces and special chars', async () => {
    const { NewModernization } = await import('../pages/NewModernization');
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    const file = new File(['content'], 'My COBOL App!.zip', { type: 'application/zip' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await vi.waitFor(() => {
      expect(screen.getByDisplayValue('my-cobol-app')).toBeInTheDocument();
    });
  });

  it('shows "Detected from uploaded archive" hint after auto-fill', async () => {
    const { NewModernization } = await import('../pages/NewModernization');
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    const file = new File(['content'], 'legacy-app.zip', { type: 'application/zip' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await vi.waitFor(() => {
      expect(screen.getByText('Detected from uploaded archive')).toBeInTheDocument();
    });
  });

  it('auto-fill does not overwrite user-edited name', async () => {
    const { NewModernization } = await import('../pages/NewModernization');
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    // User edits name first
    const nameInput = screen.getByLabelText(/Application Name/);
    fireEvent.change(nameInput, { target: { value: 'custom-name' } });

    // Then uploads ZIP
    const file = new File(['content'], 'other-app.zip', { type: 'application/zip' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    // Name should NOT change — user edit is preserved
    expect(nameInput).toHaveValue('custom-name');
  });

  it('hides hint when user edits name after auto-fill', async () => {
    const { NewModernization } = await import('../pages/NewModernization');
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    // Upload ZIP to trigger auto-fill
    const file = new File(['content'], 'auto-app.zip', { type: 'application/zip' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await vi.waitFor(() => {
      expect(screen.getByText('Detected from uploaded archive')).toBeInTheDocument();
    });

    // User edits name → hint should disappear
    const nameInput = screen.getByLabelText(/Application Name/);
    fireEvent.change(nameInput, { target: { value: 'user-edited' } });

    expect(screen.queryByText('Detected from uploaded archive')).not.toBeInTheDocument();
  });

  it('can submit after auto-fill', async () => {
    const { NewModernization } = await import('../pages/NewModernization');
    const onSubmit = vi.fn();
    render(<NewModernization onSubmit={onSubmit} />);

    const file = new File(['content'], 'submit-app.zip', { type: 'application/zip' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await vi.waitFor(() => {
      expect(screen.getByDisplayValue('submit-app')).toBeInTheDocument();
    });

    const submitBtn = screen.getByRole('button', { name: /Start Modernization/ });
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledWith({
      name: 'submit-app',
      workloadId: 'wl-submit-app',
      description: '',
      zipFile: file,
    });
  });
});
