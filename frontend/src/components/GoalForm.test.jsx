import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import GoalForm from './GoalForm'

const values = { name: 'Holiday', type: 'savings', priority: 'medium', targetAmount: '1000', currentAmount: '0', deadlineDate: '', autoRule: '' }

describe('GoalForm deletion', () => {
  it('only offers deletion for an existing goal and never submits the form', () => {
    const onDelete = vi.fn()
    const onSubmit = vi.fn()
    const props = { values, onChange: vi.fn(), onSubmit }
    const { rerender } = render(<GoalForm {...props} />)
    expect(screen.queryByRole('button', { name: 'Delete goal' })).not.toBeInTheDocument()
    rerender(<GoalForm {...props} onDelete={onDelete} />)
    fireEvent.click(screen.getByRole('button', { name: 'Delete goal' }))
    expect(onDelete).toHaveBeenCalledOnce()
    expect(onSubmit).not.toHaveBeenCalled()
    rerender(<GoalForm {...props} onDelete={onDelete} loading />)
    expect(screen.getByRole('button', { name: 'Delete goal' })).toBeDisabled()
  })
})
