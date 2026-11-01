import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ModernDashboard from './ModernDashboard'
import {
  formatRailCalendarDate,
  formatRailCalendarLabel,
  formatRailWeekday,
} from '../utils/calendarDate'

const baseProps = {
  userName: 'Haitham',
  currentCycle: { cycle_name: 'August', income_amount: 30000 },
  budgetData: {
    current_daily_allowance: 1503,
    remaining_total_budget: 12022,
    remaining_days: 8,
    total_days: 31,
  },
  analysis: { total_spent: 77947, by_category: [] },
  goals: [],
  paymentSummary: { outstanding_credit_card: 4350, outstanding_count: 3 },
  creditCardExpenses: [],
  dailyTable: [
    {
      date: '2026-08-23',
      status: 'actual',
      available_today: 1503,
      used_today: 280,
      remaining_today: 1223,
    },
  ],
  recentExpenses: [],
  budgetAddition: '',
  setBudgetAddition: vi.fn(),
  onAddBudget: vi.fn(),
  onOpenAsk: vi.fn(),
  onRecordSpending: vi.fn(),
  onOpenSettings: vi.fn(),
  onLogout: vi.fn(),
  onOpenSpending: vi.fn(),
  onOpenBudget: vi.fn(),
  onOpenGoals: vi.fn(),
  onOpenGoal: vi.fn(),
  onCreateGoal: vi.fn(),
  onOpenCard: vi.fn(),
  onOpenDay: vi.fn(),
}

describe('ModernDashboard', () => {
  it('updates the home balance and percentage from today after spending', () => {
    const now = new Date()
    const date = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join('-')
    const day = { date, status: 'actual', available_today: 1554.5, remaining_today: 1554.5, used_today: 0 }
    const { container, rerender } = render(<ModernDashboard {...baseProps} dailyTable={[day]} />)
    expect(container.querySelector('.editorial-safe-value')).toHaveTextContent('1,554.50')
    expect(screen.getByText('100% left today')).toBeInTheDocument()
    rerender(<ModernDashboard {...baseProps} dailyTable={[{ ...day, used_today: 214.99, remaining_today: 1339.51 }]} />)
    expect(container.querySelector('.editorial-safe-value')).toHaveTextContent('1,339.51')
    expect(screen.getByText('86% left today')).toBeInTheDocument()
    rerender(<ModernDashboard {...baseProps} dailyTable={[{ ...day, used_today: 1600, remaining_today: -45.5 }]} />)
    expect(screen.getByText('0% left today')).toBeInTheDocument()
    expect(screen.queryByText('On track')).not.toBeInTheDocument()
  })

  it('keeps currency separate and opens one financial card inline', () => {
    render(<ModernDashboard {...baseProps} />)

    expect(screen.getAllByText('EGP').length).toBeGreaterThan(0)
    const budgetCard = screen.getByRole('button', { name: /Budget left/i })
    const spentCard = screen.getByRole('button', { name: /Spent/i })
    fireEvent.click(budgetCard)
    const budgetDetails = screen.getByText(/Budget left is calculated/i)
    expect(budgetDetails).toBeInTheDocument()
    expect(budgetCard.compareDocumentPosition(budgetDetails)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(budgetDetails.compareDocumentPosition(spentCard)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)

    fireEvent.click(spentCard)
    expect(screen.queryByText(/Budget left is calculated/i)).not.toBeInTheDocument()
  })

  it('opens the full destination from expanded cards', () => {
    render(<ModernDashboard {...baseProps} />)

    fireEvent.click(screen.getByRole('button', { name: /Budget left/i }))
    fireEvent.click(screen.getByRole('button', { name: /^View all/i }))
    expect(baseProps.onOpenBudget).toHaveBeenCalledOnce()

    fireEvent.click(screen.getByRole('button', { name: /Goals/i }))
    const viewAllButtons = screen.getAllByRole('button', { name: /^View all/i })
    fireEvent.click(viewAllButtons.at(-1))
    expect(baseProps.onOpenGoals).toHaveBeenCalledOnce()
  })

  it('shows one proportional spending bar and calculates Other from remaining categories', () => {
    const { container } = render(
      <ModernDashboard
        {...baseProps}
        currentCycle={{ ...baseProps.currentCycle, cycle_name: 'Monthly Income' }}
        analysis={{
          total_spent: 1000,
          by_category: [
            { category: 'Home', amount: 480, percentage_of_total_spent: 48 },
            { category: 'Loans', amount: 130, percentage_of_total_spent: 13 },
            { category: 'Savings', amount: 130, percentage_of_total_spent: 13 },
            { category: 'Food', amount: 160, percentage_of_total_spent: 16 },
            { category: 'Travel', amount: 100, percentage_of_total_spent: 10 },
          ],
        }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Spent/i }))

    expect(screen.getByText('Monthly Income')).toBeInTheDocument()
    expect(screen.getAllByText('Other').length).toBeGreaterThan(0)
    expect(screen.getAllByText('26%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('EGP 260').length).toBeGreaterThan(0)
    expect(container.querySelectorAll('.editorial-spending-bar')).toHaveLength(1)
    expect(container.querySelectorAll('.editorial-spending-segment')).toHaveLength(4)
    expect(container.querySelectorAll('.editorial-spending-callout')).toHaveLength(4)
    expect(container.querySelectorAll('.editorial-category-grid')).toHaveLength(0)

    const segmentWidths = [...container.querySelectorAll('.editorial-spending-segment')]
      .map((segment) => Number.parseFloat(segment.style.width))
    expect(segmentWidths.reduce((total, width) => total + width, 0)).toBeCloseTo(100)
    expect(container.querySelectorAll('.editorial-spending-segment.is-above')).toHaveLength(2)
    expect(container.querySelectorAll('.editorial-spending-segment.is-below')).toHaveLength(2)
  })

  it('updates all expanded spending content when the selected cycle changes', () => {
    const { rerender } = render(
      <ModernDashboard
        {...baseProps}
        recentExpenses={[{
          id: 1,
          subcategory_name: 'Groceries',
          expense_date: '2026-08-23',
          amount: 300,
        }]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Spent/i }))
    expect(screen.getByText('August')).toBeInTheDocument()
    expect(screen.getByText('Groceries')).toBeInTheDocument()

    rerender(
      <ModernDashboard
        {...baseProps}
        currentCycle={{ cycle_name: 'A very long selected financial cycle name' }}
        analysis={{
          total_spent: 500,
          by_category: [{ category: 'Transport', amount: 500, percentage_of_total_spent: 100 }],
        }}
        recentExpenses={[{
          id: 2,
          subcategory_name: 'Fuel',
          expense_date: '2026-09-02',
          amount: 500,
        }]}
      />,
    )

    expect(screen.getByTitle('A very long selected financial cycle name')).toBeInTheDocument()
    expect(screen.getAllByText('Transport').length).toBeGreaterThan(0)
    expect(screen.getByText('Fuel')).toBeInTheDocument()
    expect(screen.queryByText('Groceries')).not.toBeInTheDocument()
  })

  it('uses the cycle fallback and keeps an empty cycle empty', () => {
    render(
      <ModernDashboard
        {...baseProps}
        currentCycle={{ cycle_name: '   ' }}
        analysis={{ total_spent: 0, by_category: [] }}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Spent/i }))

    expect(screen.getByText('Current cycle')).toBeInTheDocument()
    expect(screen.getByText('No spending recorded in this cycle yet.')).toBeInTheDocument()
    expect(screen.queryByText('Other')).not.toBeInTheDocument()
  })

  it('does not report on track when no budget remains', () => {
    render(
      <ModernDashboard
        {...baseProps}
        budgetData={{
          ...baseProps.budgetData,
          current_daily_allowance: 0,
          remaining_total_budget: 0,
        }}
      />,
    )

    expect(screen.queryByText('On track')).not.toBeInTheDocument()
    expect(screen.getAllByText('No budget left')).toHaveLength(2)
  })

  it("distinguishes today's zero allowance from an exhausted cycle budget", () => {
    render(
      <ModernDashboard
        {...baseProps}
        budgetData={{
          ...baseProps.budgetData,
          current_daily_allowance: 0,
          remaining_total_budget: 500,
        }}
      />,
    )

    expect(screen.queryByText('No budget left')).not.toBeInTheDocument()
    expect(screen.getAllByText("Today's limit reached")).toHaveLength(2)
  })

  it('uses RTL layout for Arabic', () => {
    const localNow = new Date()
    const { container } = render(<ModernDashboard {...baseProps} language="ar" />)
    expect(container.querySelector('main')).toHaveAttribute('dir', 'rtl')
    const rail = screen.getByRole('img', { name: formatRailCalendarLabel(localNow, 'ar') })
    expect(within(rail).getByText(formatRailWeekday(localNow, 'ar'))).toBeInTheDocument()
  })

  it('uses the application privacy state and delegates switch changes', () => {
    const onAmountsHiddenChange = vi.fn()
    const { container } = render(
      <ModernDashboard
        {...baseProps}
        amountsHidden
        onAmountsHiddenChange={onAmountsHiddenChange}
      />,
    )

    expect(container.querySelector('main')).toHaveClass('amounts-hidden')
    const privacySwitch = screen.getByRole('switch', { name: /Show amounts/i })
    expect(privacySwitch).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(privacySwitch)
    expect(onAmountsHiddenChange).toHaveBeenCalledWith(false)
  })

  it.each([
    ['JAN', 0], ['FEB', 1], ['MAR', 2], ['APR', 3], ['MAY', 4], ['JUN', 5],
    ['JUL', 6], ['AUG', 7], ['SEP', 8], ['OCT', 9], ['NOV', 10], ['DEC', 11],
  ])('formats %s from the local calendar month', (month, monthIndex) => {
    expect(formatRailCalendarDate(new Date(2026, monthIndex, 15, 12))).toEqual({
      day: 15,
      month,
      year: 2026,
    })
  })

  it('formats February correctly in leap and non-leap years', () => {
    expect(formatRailCalendarDate(new Date(2024, 1, 29, 12))).toEqual({
      day: 29,
      month: 'FEB',
      year: 2024,
    })
    expect(formatRailCalendarDate(new Date(2023, 1, 28, 12))).toEqual({
      day: 28,
      month: 'FEB',
      year: 2023,
    })
  })

  it.each([
    ['SUNDAY', 23], ['MONDAY', 24], ['TUESDAY', 25], ['WEDNESDAY', 26],
    ['THURSDAY', 27], ['FRIDAY', 28], ['SATURDAY', 29],
  ])('formats the full local weekday %s', (weekday, day) => {
    expect(formatRailWeekday(new Date(2026, 7, day, 12))).toBe(weekday)
  })

  it.each([
    ['الأحد', 23], ['الاثنين', 24], ['الثلاثاء', 25], ['الأربعاء', 26],
    ['الخميس', 27], ['الجمعة', 28], ['السبت', 29],
  ])('formats the localized Arabic weekday %s', (weekday, day) => {
    expect(formatRailWeekday(new Date(2026, 7, day, 12), 'ar')).toBe(weekday)
  })

  it('provides one complete readable rail label', () => {
    expect(formatRailCalendarLabel(new Date(2026, 7, 25, 12))).toBe(
      'Today is Tuesday, August 25, 2026.',
    )
  })

  it('formats localized Arabic rail content without rotating its words', () => {
    const date = new Date(2026, 7, 26, 12)
    expect(formatRailWeekday(date, 'ar')).toBe('الأربعاء')
    expect(formatRailCalendarDate(date, 'ar')).toEqual({
      day: 26,
      month: 'أغسطس',
      year: 2026,
    })
    expect(formatRailCalendarLabel(date, 'ar')).toBe(
      'اليوم الأربعاء، 26 أغسطس 2026.',
    )
  })

  it('keeps the rail date independent from Daily Pace selection', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 7, 25, 12, 0, 0))

    try {
      render(
        <ModernDashboard
          {...baseProps}
          dailyTable={[
            { ...baseProps.dailyTable[0], date: '2026-08-22' },
            { ...baseProps.dailyTable[0], date: '2026-08-23' },
          ]}
        />,
      )

      const rail = screen.getByLabelText('Today is Tuesday, August 25, 2026.')
      expect(within(rail).getByText('TUESDAY')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: /Daily pace/i }))
      fireEvent.click(screen.getByRole('button', { name: /August 22/i }))

      expect(screen.getByLabelText('Today is Tuesday, August 25, 2026.')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('updates the rail automatically at the next local midnight', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 7, 25, 23, 59, 59, 900))

    try {
      render(<ModernDashboard {...baseProps} />)
      expect(screen.getByLabelText('Today is Tuesday, August 25, 2026.')).toBeInTheDocument()

      act(() => {
        vi.advanceTimersByTime(200)
      })

      expect(screen.getByLabelText('Today is Wednesday, August 26, 2026.')).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
