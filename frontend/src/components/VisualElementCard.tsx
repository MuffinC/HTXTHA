// One AI description of a visual element (photo, chart, table, ...).
//
// Observations, possible inferences (each with its basis) and information gaps
// are kept visibly separate (principle 4). Graphic content is collapsed until
// the analyst chooses to reveal it.
import { useState } from 'react';
import type { VisualElement } from '../api/types';
import { PII_LABEL, VISUAL_TYPE_LABEL } from '../lib/labels';
import { parseMarkdownTable } from '../lib/markdown';
import { CitationChip } from './Citations';
import { AiLabel } from './Common';
import { Icon } from './Icon';
import { SceneGrid } from './IncidentSections';
import { ModelText } from './ModelText';

function KeyValue({ value }: { value: string }) {
  const [label, ...rest] = value.split(':');
  const reading = rest.join(':').trim();
  if (!reading) return <ModelText text={value} />;
  const estimated = reading.startsWith('~');
  return (
    <>
      <span>{label}</span>
      <span className="num" title={estimated ? 'Estimated from the chart gridlines' : undefined}>
        {reading}
        {estimated && <span className="visually-hidden"> (estimated)</span>}
      </span>
    </>
  );
}

function Lists({ element }: { element: VisualElement }) {
  const { observations, possible_inferences, information_gaps } = element;
  if (!observations.length && !possible_inferences.length && !information_gaps.length) return null;
  return (
    <div className="evidence">
      <div>
        <h5>Observations</h5>
        {observations.length ? (
          <ul>{observations.map((o, i) => <li key={i}><ModelText text={o} /></li>)}</ul>
        ) : (
          <p className="muted small">None recorded.</p>
        )}
      </div>
      <div>
        <h5>Possible inferences</h5>
        {possible_inferences.length ? (
          <ul>
            {possible_inferences.map((p, i) => (
              <li key={i}>
                <ModelText text={p.inference} />
                <span className="basis">
                  Basis: <ModelText text={p.basis} />
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">None.</p>
        )}
      </div>
      <div>
        <h5>Information gaps</h5>
        {information_gaps.length ? (
          <ul>{information_gaps.map((g, i) => <li key={i}><ModelText text={g} /></li>)}</ul>
        ) : (
          <p className="muted small">None recorded.</p>
        )}
      </div>
    </div>
  );
}

function Body({ element }: { element: VisualElement }) {
  const table = element.table_markdown ? parseMarkdownTable(element.table_markdown) : null;
  return (
    <>
      <p className="visual-description">
        <ModelText text={element.description} />
      </p>
      {element.scene && <SceneGrid scene={element.scene} />}
      {element.chart && (
        <div className="chart-details">
          <p className="muted small">
            {element.chart.chart_type} chart · x: {element.chart.x_axis} · y: {element.chart.y_axis}
          </p>
          {element.chart.key_values.length > 0 && (
            <dl className="key-values">
              {element.chart.key_values.map((v, i) => (
                <div key={i}>
                  <KeyValue value={v} />
                </div>
              ))}
            </dl>
          )}
          <p>
            <span className="muted">Trend: </span>
            <ModelText text={element.chart.trend} />
          </p>
        </div>
      )}
      {element.table_markdown &&
        (table ? (
          <div className="table-wrap">
            <table>
              <tbody>
                {table.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) =>
                      r === 0 ? <th key={c}>{cell}</th> : <td key={c}>{cell}</td>,
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <pre className="pre">{element.table_markdown}</pre>
        ))}
      {element.transcription && (
        <blockquote className="transcription">
          <ModelText text={element.transcription} />
        </blockquote>
      )}
      <Lists element={element} />
      {element.sensitive_content.pii_visible.length > 0 && (
        <p className="muted small pii-line">
          <Icon name="eye" /> Visible personal information (not transcribed):{' '}
          {element.sensitive_content.pii_visible.map((p) => PII_LABEL[p]).join(', ')}
        </p>
      )}
    </>
  );
}

export function VisualElementCard({
  element,
  documentId,
}: {
  element: VisualElement;
  documentId: string;
}) {
  const graphic = element.sensitive_content.graphic;
  const [revealed, setRevealed] = useState(!graphic);
  return (
    <article className="visual-card">
      <header className="visual-head">
        <span className="visual-type">{VISUAL_TYPE_LABEL[element.type]}</span>
        <CitationChip citation={{ document_id: documentId, page: element.page }} />
        <AiLabel />
      </header>
      {revealed ? (
        <Body element={element} />
      ) : (
        <div className="graphic-cover">
          <Icon name="eye" />
          <span>Graphic content: description hidden.</span>
          <button type="button" className="button-secondary small" onClick={() => setRevealed(true)}>
            Show description
          </button>
        </div>
      )}
    </article>
  );
}
