// The scene grid of an incident photo. An empty list is "no answer from the model",
// which must not read as "no damage" (D-080); "none visible" is its own value.
import { render, screen } from '@testing-library/react';
import type { SceneObservation } from '../api/types';
import { SceneGrid } from './IncidentSections';

const BASE: SceneObservation = {
  lighting: 'daylight',
  weather: 'clear',
  road_surface: 'dry',
  vehicles_visible: '1',
  vehicle_types: ['car'],
  damage_locations: ['front'],
  traffic_signal: 'not_visible',
  timestamp_visible: null,
};

function damageCell(): HTMLElement {
  const term = screen.getByText('Damage');
  return term.nextElementSibling as HTMLElement;
}

describe('SceneGrid damage row', () => {
  it('shows an empty list as "not reported", muted, never as "none"', () => {
    render(<SceneGrid scene={{ ...BASE, damage_locations: [] }} />);
    expect(damageCell()).toHaveTextContent('not reported');
    expect(damageCell().parentElement).toHaveClass('is-unclear');
  });

  it('shows "none visible" when the model says so', () => {
    render(<SceneGrid scene={{ ...BASE, damage_locations: ['none_visible'] }} />);
    expect(damageCell()).toHaveTextContent('none visible');
  });

  it('shows the damage locations', () => {
    render(<SceneGrid scene={BASE} />);
    expect(damageCell()).not.toHaveTextContent('not reported');
    expect(damageCell().parentElement).not.toHaveClass('is-unclear');
  });
});
