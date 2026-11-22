// Triage badge, analyst confirm/override, group priority and section feedback,
// rendered from the real mock-mode incident fixture (five sample tickets, one
// of them already overridden by an analyst).
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from './App';
import type { JobResponse } from './api/types';
import jobIncident from './test/fixtures/jobIncident';
import { mockApi, setUrl } from './test/mockApi';

const byName = (name: string) => jobIncident.documents.find((d) => d.filename === name)!;
const triagePanel = () => screen.findByRole('region', { name: 'Triage' });

function withoutReview(): JobResponse {
  const job = structuredClone(jobIncident);
  job.documents.forEach((d) => {
    if (d.analysis?.triage) d.analysis.triage.analyst_override = null;
  });
  return job;
}

function putCalls(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT');
}

describe('triage', () => {
  it('shows a weapon as P1 from the rule floor, with its page chip', async () => {
    const t5 = byName('t5_weapon_variant.pdf');
    mockApi({ jobs: { [jobIncident.job_id]: jobIncident } });
    setUrl({ job: jobIncident.job_id, tab: t5.document_id });
    render(<App />);

    const panel = await triagePanel();
    expect(within(panel).getByTitle(/Ongoing danger to life/)).toHaveTextContent('SuggestedP1Urgent');
    expect(panel).toHaveTextContent('rule floor P1');
    expect(panel).not.toHaveTextContent('raised by the model');
    expect(panel).toHaveTextContent('needs analyst review');
    const factor = within(panel).getByText('Weapon reported').closest('li')!;
    expect(within(factor).getByText('Rule-based')).toBeInTheDocument();
    expect(within(factor).getByRole('button', { name: /^Open page 1/ })).toBeInTheDocument();
  });

  it('labels a model raise as AI with its checked quote', async () => {
    const job = structuredClone(jobIncident);
    const t4 = job.documents.find((d) => d.filename === 't4_unrelated_tree.pdf')!;
    const triage = t4.analysis!.triage!;
    triage.model_priority = 'P1';
    triage.suggested_priority = 'P1';
    triage.triggering_factors.push({
      factor: 'Danger to life (“hit a roadside tree”)',
      citation: { document_id: t4.document_id, page: 1 },
      source: 'model',
    });
    mockApi({ jobs: { [job.job_id]: job } });
    setUrl({ job: job.job_id, tab: t4.document_id });
    render(<App />);

    const panel = await triagePanel();
    expect(panel).toHaveTextContent('rule floor P3 · raised by the model to P1');
    const factor = within(panel).getByText(/hit a roadside tree/).closest('li')!;
    expect(within(factor).getByText('AI, quote checked')).toBeInTheDocument();
  });

  it('shows the analyst decision next to the suggestion', async () => {
    const t1 = byName('t1_witness.pdf');
    mockApi({ jobs: { [jobIncident.job_id]: jobIncident } });
    setUrl({ job: jobIncident.job_id, tab: t1.document_id });
    render(<App />);

    const panel = await triagePanel();
    expect(panel).toHaveTextContent('SuggestedP3');
    expect(panel).toHaveTextContent('AnalystP2');
    expect(panel).toHaveTextContent('Same incident as the P2 reports');
  });

  it('confirms the suggestion and reloads the job', async () => {
    const t2 = byName('t2_taxi_driver.pdf');
    const reviewed = withoutReview();
    reviewed.documents[1]!.analysis!.triage!.analyst_override = {
      action: 'confirm',
      priority: 'P2',
      reason: 'Confirmed the suggested priority.',
      at: '2026-01-01T09:05:00Z',
    };
    const fetchMock = mockApi({ jobs: { [jobIncident.job_id]: [withoutReview(), reviewed] } });
    setUrl({ job: jobIncident.job_id, tab: t2.document_id });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Confirm P2' }));
    expect(await screen.findByText(/Confirmed the suggested priority/)).toBeInTheDocument();
    const [[url, init]] = putCalls(fetchMock) as [[string, RequestInit]];
    expect(url).toBe(`/api/jobs/${jobIncident.job_id}/documents/${t2.document_id}/triage`);
    expect(JSON.parse(String(init.body))).toEqual({ action: 'confirm' });
  });

  it('requires a reason before sending an override', async () => {
    const t4 = byName('t4_unrelated_tree.pdf');
    const fetchMock = mockApi({ jobs: { [jobIncident.job_id]: withoutReview() } });
    setUrl({ job: jobIncident.job_id, tab: t4.document_id });
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name: 'Override…' }));
    fireEvent.change(screen.getByLabelText('New priority'), { target: { value: 'P1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save override' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Give a reason');
    expect(putCalls(fetchMock)).toHaveLength(0);

    fireEvent.change(screen.getByLabelText('Reason (required)'), {
      target: { value: '  Tree blocking an ambulance route  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save override' }));
    await waitFor(() => expect(putCalls(fetchMock)).toHaveLength(1));
    expect(JSON.parse(String(putCalls(fetchMock)[0]![1]!.body))).toEqual({
      action: 'override',
      priority: 'P1',
      reason: 'Tree blocking an ambulance route',
    });
  });

  it('shows a server error when the decision cannot be saved', async () => {
    const t4 = byName('t4_unrelated_tree.pdf');
    mockApi({
      jobs: { [jobIncident.job_id]: withoutReview() },
      triage: [404, { error: { code: 'NOT_FOUND', message: 'No such job or document.', details: {} } }],
    });
    setUrl({ job: jobIncident.job_id, tab: t4.document_id });
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm P3' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No such job or document.');
  });

  it('shows the group priority and why it was lifted in the consolidated report', async () => {
    mockApi({ jobs: { [jobIncident.job_id]: jobIncident } });
    setUrl({ job: jobIncident.job_id });
    render(<App />);

    const group = await screen.findByRole('region', { name: 'Same incident' });
    expect(within(group).getByText('Group')).toBeInTheDocument();
    expect(group).toHaveTextContent('GroupP2High');
    expect(group).toHaveTextContent(/Weather \(does not lift\)/);
  });

  it('has no triage panel in the general profile', async () => {
    const job = withoutReview();
    job.documents.forEach((d) => {
      if (d.analysis) d.analysis.triage = null;
    });
    mockApi({ jobs: { [job.job_id]: job } });
    setUrl({ job: job.job_id, tab: job.documents[0]!.document_id });
    render(<App />);
    await screen.findByRole('region', { name: 'Document summary' });
    expect(screen.queryByRole('region', { name: 'Triage' })).not.toBeInTheDocument();
  });
});

describe('section feedback', () => {
  it('sends a rating with a stable section ID and marks the choice', async () => {
    const fetchMock = mockApi({ jobs: { [jobIncident.job_id]: jobIncident } });
    setUrl({ job: jobIncident.job_id });
    render(<App />);

    const summary = await screen.findByRole('region', { name: 'Overall summary' });
    const up = within(summary).getByRole('button', { name: 'Overall summary is helpful' });
    fireEvent.click(up);
    await waitFor(() => expect(up).toHaveAttribute('aria-pressed', 'true'));
    expect(within(summary).getByText('Thanks')).toBeInTheDocument();

    const post = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/feedback'))!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({
      target: 'section',
      target_id: 'consolidated.overall_summary',
      rating: 'up',
    });
  });

  it('says when a rating could not be saved', async () => {
    mockApi({
      jobs: { [jobIncident.job_id]: jobIncident },
      feedback: [500, { error: { code: 'INTERNAL', message: 'x', details: {} } }],
    });
    setUrl({ job: jobIncident.job_id });
    render(<App />);
    const summary = await screen.findByRole('region', { name: 'Overall summary' });
    fireEvent.click(within(summary).getByRole('button', { name: 'Overall summary is not helpful' }));
    expect(await within(summary).findByText('Not saved')).toBeInTheDocument();
  });
});
