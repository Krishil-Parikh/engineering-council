import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { LiveTerminal } from './LiveTerminal';

describe('LiveTerminal', () => {
  it('shows an agent\'s commands, failures and notes as terminal lines with their times', () => {
    render(<LiveTerminal agentName="DEV_2" lines={['10:01:02 $ pytest -q', '10:01:05   exit 1', '10:01:06 ! File not found: a.py', '10:01:07 # fixing the import']} />);
    const terminal = screen.getByRole('log', { name: 'Live terminal: DEV_2' });
    expect(within(terminal).getByText('$ pytest -q')).toBeInTheDocument();
    expect(within(terminal).getByText('10:01:02')).toBeInTheDocument();
    expect(within(terminal).getByText('! File not found: a.py')).toBeInTheDocument();
    expect(within(terminal).getByText('# fixing the import')).toBeInTheDocument();
  });

  it('says so while the agent has not run anything yet', () => {
    render(<LiveTerminal agentName="DEV_5" lines={[]} />);
    expect(screen.getByText(/Waiting for DEV_5 to run something/)).toBeInTheDocument();
  });
});
