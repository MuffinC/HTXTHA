// App-level tests rendered from real API fixtures (captured from the backend in mock mode).
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { vi } from 'vitest';
import App from './App';
import type { JobResponse } from './api/types';
import jobCompleted from './test/fixtures/jobCompleted';
import jobFailed from './test/fixtures/jobFailed';
import jobPartial from './test/fixtures/jobPartial';
import { mockApi, pdfFile, setUrl } from './test/mockApi';

const ID = jobCompleted.job_id;

function clone(job: JobResponse): JobResponse {
  return structuredClone(job);
}

/** The completed fixture, rewound to mid-processing (first document describing visuals). */
function processing(): JobResponse {
  const job = clone(jobCompleted);
  job.status = 'processing';
  job.consolidated = null;
  job.documents.forEach((d, i) => {
    d.status = i === 0 ? 'analysing_visuals' : 'queued';
    d.analysis = null;
  });
  return job;
}

beforeEach(() => setUrl({}));

describe('idle and app-wide states', () => {
  it('shows the explainer, mock badge and mock strip in mock mode', async () => {
    mockApi();
    render(<App />);

    expect(screen.getByRole('heading', { name: 'Analyse documents locally' })).toBeInTheDocument();
    expect(await screen.findByText('Mock provider')).toBeInTheDocument();
    expect(screen.getByText(/Results are generated samples/)).toBeInTheDocument();
    expect(await screen.findByText(/Up to 10 files · 25 MB and 60 pages each/)).toBeInTheDocument();
  });

  it('shows a banner and disables analysis when the backend is unreachable', async () => {
    mockApi({ health: 'down' });
    render(<App />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Can’t reach the backend');
    expect(screen.getByText('Backend unreachable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Analyse' })).toBeDisabled();
  });

  it('waits for the backend when a job link is opened while it is down', async () => {
    mockApi({ health: 'down' });
    setUrl({ job: ID });
    render(<App />);
    expect(await screen.findByText('Waiting for the backend')).toBeInTheDocument();
  });

  it('blocks analysis with a reason while the model is not ready', async () => {
    mockApi({ health: { status: 'degraded', provider: 'ollama', model: 'qwen3-vl:4b-instruct', model_ready: false } });
    render(<App />);
    await screen.findByText('Model not ready');
    await screen.findByText(/Up to 10 files/);

    fireEvent.change(screen.getByTestId('file-input'), { target: { files: [pdfFile('a.pdf')] } });

    const button = await screen.findByRole('button', { name: 'Analyse 1 document' });
    expect(button).toBeDisabled();
    expect(screen.getByText(/The model is not ready yet/)).toBeInTheDocument();
  });
});

describe('upload', () => {
  it('lists client-side rejections per file and uploads only valid files', async () => {
    const fetchMock = mockApi({ jobs: { [ID]: jobCompleted } });
    render(<App />);
    await screen.findByText(/Up to 10 files/);

    const fake = new File(['plain text'], 'notes.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByTestId('file-input'), {
      target: { files: [pdfFile('report.pdf'), fake] },
    });

    const list = await screen.findByRole('list', { name: 'Selected files' });
    expect(within(list).getByText(/Not a PDF/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Analyse 1 document' }));

    await waitFor(() => expect(window.location.search).toContain('job='));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    const form = post?.[1]?.body as FormData;
    expect((form.getAll('files') as File[]).map((f) => f.name)).toEqual(['report.pdf']);
    expect(form.get('profile')).toBe('general');
  });

  it('shows the server’s reason for each file when every file is rejected', async () => {
    mockApi({
      createJob: [
        400,
        {
          error: {
            code: 'NO_VALID_FILES',
            message: 'None of the uploaded files could be accepted.',
            details: { rejected: [{ filename: 'locked.pdf', code: 'ENCRYPTED_PDF', message: 'The PDF is password-protected.' }] },
          },
        },
      ],
    });
    render(<App />);
    await screen.findByText(/Up to 10 files/);
    fireEvent.change(screen.getByTestId('file-input'), { target: { files: [pdfFile('locked.pdf')] } });
    fireEvent.click(await screen.findByRole('button', { name: 'Analyse 1 document' }));

    const rejected = await screen.findByRole('list', { name: 'Files rejected by the server' });
    expect(within(rejected).getByText(/Password-protected: The PDF is password-protected/)).toBeInTheDocument();
    expect(screen.getByText('None of the files could be accepted.')).toBeInTheDocument();
  });

  it('only offers available profiles', async () => {
    mockApi();
    render(<App />);
    expect(await screen.findByRole('option', { name: 'Incident (coming later)' })).toBeDisabled();
    expect(screen.getByRole('option', { name: 'General' })).toBeEnabled();
  });
});

describe('results from a completed job', () => {
  it('reloads the job from the URL and opens the consolidated report first', async () => {
    mockApi({ jobs: { [ID]: jobCompleted } });
    setUrl({ job: ID });
    render(<App />);

    expect(await screen.findByRole('tab', { name: 'Consolidated report', selected: true })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Consolidated report' })).toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getByText('Time of the incident')).toBeInTheDocument();
    // Citations show the document label (D1/D2 mapped from real IDs).
    expect(within(table).getByRole('button', { name: /Open page 1 of report_a.pdf/ })).toHaveTextContent('D1 p.1');
  });

  it('shows a document’s analysis, keeps the tab in the URL, and opens the page drawer', async () => {
    mockApi({ jobs: { [ID]: jobCompleted } });
    setUrl({ job: ID });
    render(<App />);

    fireEvent.click(await screen.findByRole('tab', { name: /D1 report_a.pdf/ }));
    expect(screen.getByRole('heading', { name: 'report_a.pdf' })).toBeInTheDocument();
    expect(window.location.search).toContain(`tab=${jobCompleted.documents[0]!.document_id}`);
    expect(screen.getByText('Locations')).toBeInTheDocument();
    expect(screen.getAllByText('AI-generated').length).toBeGreaterThan(1);
    expect(screen.getByText('Photo')).toBeInTheDocument();
    expect(screen.getByText(/Visible personal information/)).toHaveTextContent('licence plate');

    fireEvent.click(screen.getAllByRole('button', { name: 'Open page 2 of report_a.pdf' })[0]!);
    const drawer = await screen.findByRole('dialog');
    expect(within(drawer).getByRole('heading', { name: /Page 2/ })).toBeInTheDocument();
    expect(within(drawer).getByText(/Sample photo on page 2/)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('flags security warnings on the document and its tab', async () => {
    mockApi({ jobs: { [ID]: jobCompleted } });
    setUrl({ job: ID, tab: jobCompleted.documents[2]!.document_id });
    render(<App />);

    expect(await screen.findByText(/includes a security warning/)).toBeInTheDocument();
    expect(screen.getAllByText('Possible prompt injection').length).toBe(2);
  });

  it('collapses graphic visual content until the analyst reveals it', async () => {
    const job = clone(jobCompleted);
    job.documents[0]!.analysis!.visual_elements[0]!.sensitive_content.graphic = true;
    mockApi({ jobs: { [ID]: job } });
    setUrl({ job: ID, tab: job.documents[0]!.document_id });
    render(<App />);

    expect(await screen.findByText('Graphic content: description hidden.')).toBeInTheDocument();
    expect(screen.queryByText(/Sample photo on page 2/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show description' }));
    expect(screen.getByText(/Sample photo on page 2/)).toBeInTheDocument();
  });

  it('renders masked PII as a pill, not as document text', async () => {
    const job = clone(jobCompleted);
    job.documents[0]!.analysis!.summary = 'Reporter phone [PHONE REDACTED] was given.';
    mockApi({ jobs: { [ID]: job } });
    setUrl({ job: ID, tab: job.documents[0]!.document_id });
    render(<App />);
    expect(await screen.findByText('phone redacted')).toHaveClass('redacted');
  });
});

describe('progress, partial and failed jobs', () => {
  it('polls until the job finishes and announces progress', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi({ jobs: { [ID]: [processing(), jobCompleted] } });
    setUrl({ job: ID });
    render(<App />);

    expect(await screen.findByText('Processing')).toBeInTheDocument();
    expect(screen.getByText('report_a.pdf: Describing visuals.')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: /Progress: Describing visuals/ })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100);
    });
    expect(await screen.findByText('Analysis complete.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Consolidated report' })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it('shows what succeeded and why the rest failed for a partial job', async () => {
    mockApi({ jobs: { [jobPartial.job_id]: jobPartial } });
    setUrl({ job: jobPartial.job_id });
    render(<App />);

    expect(await screen.findByText('1 of 2 documents analysed', { selector: '.notice-title' })).toBeInTheDocument();
    expect(screen.getByText(/broken_analysis.pdf/, { selector: 'strong' }).parentElement).toHaveTextContent(
      'even after one retry',
    );
    expect(screen.getByText(/1 file rejected at upload/)).toBeInTheDocument();
    expect(screen.getByText('Not a PDF.')).toBeInTheDocument(); // rejected file in the job panel
    // The successful document is still fully available.
    expect(screen.getByRole('heading', { name: 'report_a.pdf' })).toBeInTheDocument();
  });

  it('shows the reason when the whole job failed', async () => {
    mockApi({ jobs: { [jobFailed.job_id]: jobFailed } });
    setUrl({ job: jobFailed.job_id });
    render(<App />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The analysis failed');
    expect(alert).toHaveTextContent('No document could be analysed.');
    expect(screen.getByRole('button', { name: 'Start a new analysis' })).toBeInTheDocument();
  });

  it('explains an unknown job ID from a stale link', async () => {
    mockApi();
    setUrl({ job: 'does-not-exist' });
    render(<App />);
    expect(await screen.findByText('Job not found')).toBeInTheDocument();
  });
});
