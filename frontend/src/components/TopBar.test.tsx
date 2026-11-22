// The model status pill: the model name may be truncated by CSS, so the full name
// must stay available as a tooltip and to assistive technology.
import { render, screen } from '@testing-library/react';
import { TopBar } from './TopBar';

const MODEL = 'qwen3-vl:4b-instruct-with-a-long-custom-tag';

describe('TopBar model pill', () => {
  it('keeps the full model name in the tooltip of the truncating element', () => {
    render(
      <TopBar
        health={{
          reachable: true,
          health: { status: 'ok', provider: 'ollama', model: MODEL, model_ready: true },
        }}
      />,
    );
    const pill = screen.getByRole('status');
    expect(pill).toHaveTextContent(`Model ready${MODEL}`);
    expect(pill).toHaveAttribute('title', `Model ready: ${MODEL}`);
    const name = screen.getByText(MODEL);
    expect(name).toHaveClass('pill-detail'); // the element the CSS truncates
    expect(name).toHaveAttribute('title', MODEL);
  });
});
