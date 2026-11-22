// Warnings versus info-level notes (DECISIONS D-076), rendered from the real
// mock-mode fixture with its first document's warnings replaced.
import { render, screen, within } from '@testing-library/react';
import App from './App';
import type { DocumentWarning, JobResponse } from './api/types';
import jobCompleted from './test/fixtures/jobCompleted';
import { mockApi, setUrl } from './test/mockApi';

const NOTE: DocumentWarning = {
  code: 'VISUAL_NOT_DESCRIBED',
  message: 'No visual content was described on page 1; check the page if it contains a chart or image.',
  page: 1,
};
const BYTES: DocumentWarning = {
  code: 'LEADING_BYTES_IGNORED',
  message: '195 bytes before the PDF header were ignored (for example a download wrapper).',
  page: null,
};

function withWarnings(warnings: DocumentWarning[]): { job: JobResponse; docId: string } {
  const job = structuredClone(jobCompleted);
  const doc = job.documents[0]!;
  doc.analysis!.warnings = warnings;
  return { job, docId: doc.document_id };
}

async function renderDoc(warnings: DocumentWarning[]) {
  const { job, docId } = withWarnings(warnings);
  mockApi({ jobs: { [job.job_id]: job } });
  setUrl({ job: job.job_id, tab: docId });
  render(<App />);
  const toggle = await screen.findByRole('button', { name: /note|warning/ });
  return { toggle, tab: screen.getByRole('tab', { selected: true }) };
}

describe('warnings and notes', () => {
  it('shows a lone note in the info tone, without a tab badge', async () => {
    const { toggle, tab } = await renderDoc([NOTE]);
    expect(toggle).toHaveTextContent('1 note');
    expect(toggle).not.toHaveTextContent('warning');
    expect(toggle.closest('.warnings')).toHaveClass('tone-info');
    expect(screen.getByText('No visual content described')).toBeInTheDocument();
    expect(within(tab).queryByTitle(/warning/)).not.toBeInTheDocument();
  });

  it('counts warnings and notes separately and keeps the warning tone', async () => {
    const { toggle, tab } = await renderDoc([NOTE, BYTES]);
    expect(toggle).toHaveTextContent('1 warning, 1 note');
    expect(toggle.closest('.warnings')).toHaveClass('tone-warning');
    expect(screen.getByText('Bytes before the PDF header ignored')).toBeInTheDocument();
    // Only the real warning badges the tab.
    expect(within(tab).getByTitle('1 warning')).toHaveTextContent('1');
    // Warnings are listed before notes.
    const titles = screen.getAllByText(/ignored|described/, { selector: '.warning-title' });
    expect(titles.map((t) => t.textContent)).toEqual([
      expect.stringContaining('Bytes before the PDF header ignored'),
      expect.stringContaining('No visual content described'),
    ]);
  });
});
