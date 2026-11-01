import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  LogOut,
  Settings,
} from "lucide-react";
import { PulseFinancialValue } from "../pulse/PulsePrimitives";
import PulseCalendar from "../pulse/PulseCalendar";
import {
  formatRailCalendarDate,
  formatRailCalendarLabel,
  formatRailWeekday,
} from "../utils/calendarDate";

const copy = {
  en: {
    hi: "Hi", safe: "Safe to spend today", daysLeft: "days left", onTrack: "On track", noBudget: "No budget left", dailyLimit: "Today's limit reached", railDay: "Day",
    ask: "Ask Bako", askText: "Clear answers about your money", record: "Record spending",
    glance: "Money at a glance", budget: "Budget left", spent: "Spent", goals: "Goals",
    credit: "Credit due", active: "active", purchases: "purchases", pace: "Daily pace",
    cycleIncome: "Cycle income", totalSpent: "Total spent", remaining: "Remaining balance",
    remainingDays: "Remaining days", addBudget: "Add budget", currentCycle: "Current cycle", other: "Other",
    recent: "Recent", recentDays: "Recent daily activity", viewSpending: "View all spending",
    noSpending: "No spending recorded in this cycle yet.", noGoals: "No active goals yet.",
    openGoal: "Open goal", createGoal: "Create goal", saved: "saved",
    noCredit: "No outstanding credit-card purchases.", outstanding: "Outstanding",
    manageCards: "Manage cards", selectedDay: "Selected day", allowance: "Allowance",
    used: "Used", left: "Left", openDay: "Open daily details", earlier: "Earlier week",
    later: "Later week", viewAll: "View all",
    budgetNote: "Budget left is calculated by Bako from cycle income, spending and goal contributions.",
    hideAmounts: "Hide amounts", showAmounts: "Show amounts",
  },
  ar: {
    hi: "أهلاً", safe: "المتاح للصرف اليوم", daysLeft: "يوم متبقي", onTrack: "على المسار", noBudget: "لا توجد ميزانية متبقية", dailyLimit: "تم بلوغ حد اليوم", railDay: "اليوم",
    ask: "اسأل مصاريفي", askText: "إجابات واضحة عن فلوسك", record: "سجل مصروف",
    glance: "فلوسك في نظرة", budget: "المتبقي", spent: "المصروف", goals: "الأهداف",
    credit: "مستحق البطاقة", active: "نشط", purchases: "عملية", pace: "معدل الصرف اليومي",
    cycleIncome: "دخل الدورة", totalSpent: "إجمالي المصروف", remaining: "الرصيد المتبقي",
    remainingDays: "الأيام المتبقية", addBudget: "أضف للميزانية", currentCycle: "الدورة الحالية", other: "أخرى",
    recent: "الأحدث", recentDays: "النشاط اليومي الأخير", viewSpending: "عرض كل المصروفات",
    noSpending: "لا توجد مصروفات مسجلة في هذه الدورة.", noGoals: "لا توجد أهداف نشطة.",
    openGoal: "افتح الهدف", createGoal: "أنشئ هدفاً", saved: "تم توفيره",
    noCredit: "لا توجد مشتريات بطاقة غير مسددة.", outstanding: "غير مسدد",
    manageCards: "إدارة البطاقات", selectedDay: "اليوم المحدد", allowance: "المتاح",
    used: "المستخدم", left: "المتبقي", openDay: "افتح تفاصيل اليوم", earlier: "أسبوع سابق",
    later: "أسبوع لاحق", viewAll: "عرض الكل",
    budgetNote: "مصاريفي يحسب الرصيد المتبقي من دخل الدورة والمصروفات ومساهمات الأهداف.",
    hideAmounts: "إخفاء المبالغ", showAmounts: "إظهار المبالغ",
  },
};

const money = (value, language) => new Intl.NumberFormat(
  language === "ar" ? "ar-EG" : "en-US",
  { maximumFractionDigits: 0 },
).format(Number(value || 0));

const shortDate = (value, language) => {
  if (!value) return "";
  return new Intl.DateTimeFormat(language === "ar" ? "ar-EG" : "en-US", {
    month: "short",
    day: "numeric",
  }).format(new Date(`${value}T12:00:00`));
};

function useLocalCalendarDate() {
  const [currentCalendarDate, setCurrentCalendarDate] = useState(() => new Date());

  useEffect(() => {
    let midnightTimer;

    const refreshAndSchedule = () => {
      window.clearTimeout(midnightTimer);
      const now = new Date();
      setCurrentCalendarDate(now);

      const nextLocalMidnight = new Date(now);
      nextLocalMidnight.setHours(24, 0, 0, 0);
      midnightTimer = window.setTimeout(
        refreshAndSchedule,
        Math.max(1, nextLocalMidnight.getTime() - now.getTime() + 50),
      );
    };

    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refreshAndSchedule();
    };

    refreshAndSchedule();
    window.addEventListener("focus", refreshAndSchedule);
    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      window.clearTimeout(midnightTimer);
      window.removeEventListener("focus", refreshAndSchedule);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  return currentCalendarDate;
}

function MetricCard({ id, label, amount, value, meta, expanded, onToggle }) {
  return (
    <button
      type="button"
      className={`editorial-metric-card ${expanded ? "is-expanded" : ""}`}
      aria-expanded={expanded}
      aria-controls={`editorial-${id}-details`}
      onClick={() => onToggle(id)}
    >
      <span className="editorial-metric-label">{label}</span>
      <ChevronDown className="editorial-metric-chevron" size={22} />
      {amount !== undefined ? (
        <PulseFinancialValue className="editorial-metric-value editorial-private-value" amount={amount} />
      ) : (
        <strong className="editorial-metric-value editorial-private-value">{value}</strong>
      )}
      {meta && <small>{meta}</small>}
    </button>
  );
}

function MetricSlot({ children, details, expanded, id }) {
  return (
    <div className="editorial-metric-slot">
      {children}
      {expanded && (
        <section
          className="editorial-expanded-card"
          id={`editorial-${id}-details`}
          aria-live="polite"
        >
          {details}
        </section>
      )}
    </div>
  );
}

function ModernDashboard({
  language = "en", userName, currentCycle, budgetData, analysis, goals = [],
  paymentSummary, creditCardExpenses = [], dailyTable = [], recentExpenses = [],
  onOpenAsk, onRecordSpending, onOpenSettings, onLogout, onOpenSpending,
  onOpenBudget, onOpenGoals, onOpenCard, onOpenDay,
  onExpandedCardChange,
  amountsHidden = false,
  onAmountsHiddenChange,
}) {
  const t = copy[language] || copy.en;
  const isArabic = language === "ar";
  const Arrow = isArabic ? ArrowLeft : ArrowRight;
  const [expandedCard, setExpandedCard] = useState(null);
  const [paceIndex, setPaceIndex] = useState(null);
  const currentCalendarDate = useLocalCalendarDate();
  const railDate = formatRailCalendarDate(currentCalendarDate, language);
  const railWeekday = formatRailWeekday(currentCalendarDate, language);
  const railCalendarLabel = formatRailCalendarLabel(currentCalendarDate, language);
  const todayKey = [
    currentCalendarDate.getFullYear(),
    String(currentCalendarDate.getMonth() + 1).padStart(2, "0"),
    String(currentCalendarDate.getDate()).padStart(2, "0"),
  ].join("-");
  const today = dailyTable.find((day) => day.date === todayKey);
  const dailyAllowance = Number(today?.available_today ?? budgetData?.current_daily_allowance ?? 0);
  const safeDailyAllowance = Number(today?.remaining_today ?? dailyAllowance);
  const dailyPercentageLeft = dailyAllowance > 0
    ? Math.min(100, Math.max(0, (safeDailyAllowance / dailyAllowance) * 100))
    : 0;
  const percentageLabel = new Intl.NumberFormat(isArabic ? "ar-EG" : "en-US", {
    style: "percent", maximumFractionDigits: 0,
  }).format(dailyPercentageLeft / 100);
  const remainingBudget = Number(budgetData?.remaining_total_budget || 0);
  const isBudgetDepleted = remainingBudget <= 0;
  const isDailyLimitReached = safeDailyAllowance <= 0;
  const needsBudgetWarning = isBudgetDepleted || isDailyLimitReached;
  const budgetStatus = isBudgetDepleted
    ? t.noBudget
    : isDailyLimitReached
      ? t.dailyLimit
      : t.onTrack;

  const activeGoals = goals.filter((goal) => goal.status !== "completed");
  const actualDays = useMemo(
    () => dailyTable.filter((day) => day.status !== "future"),
    [dailyTable],
  );
  const effectivePaceIndex = paceIndex == null
    ? Math.max(actualDays.length - 1, 0)
    : Math.min(paceIndex, Math.max(actualDays.length - 1, 0));
  const paceDays = actualDays.slice(Math.max(0, effectivePaceIndex - 6), effectivePaceIndex + 1);
  const selectedPaceDay = actualDays[effectivePaceIndex] || null;
  const maxPaceValue = Math.max(...paceDays.map((day) => Number(day.used_today || 0)), 1);
  const outstandingExpenses = creditCardExpenses.filter((expense) => !expense.settled_at);
  const spendingCategories = (analysis?.by_category || [])
    .map((item) => ({ ...item, amount: Number(item.amount || 0) }))
    .filter((item) => item.amount > 0);
  const featuredSpendingCategories = spendingCategories.slice(0, 3);
  const otherSpendingAmount = spendingCategories
    .slice(3)
    .reduce((total, item) => total + item.amount, 0);
  const categorizedSpendingTotal = spendingCategories
    .reduce((total, item) => total + item.amount, 0);
  const rawSpendingBreakdown = [
    ...featuredSpendingCategories,
    ...(otherSpendingAmount > 0
      ? [{ category: t.other, amount: otherSpendingAmount, isOther: true }]
      : []),
  ].map((item, index) => ({
    ...item,
    color: ["#B8F22E", "#080808", "#777777", "#D8D9D6"][index % 4],
    percentage: categorizedSpendingTotal > 0
      ? (item.amount / categorizedSpendingTotal) * 100
      : 0,
  }));
  const percentageRoundingAdjustment = 100 - rawSpendingBreakdown
    .reduce((total, item) => total + Math.round(item.percentage), 0);
  const spendingBreakdown = rawSpendingBreakdown.map((item, index) => ({
    ...item,
    displayedPercentage: Math.max(
      0,
      Math.round(item.percentage) + (index === 0 ? percentageRoundingAdjustment : 0),
    ),
  }));
  const selectedCycleHeading = currentCycle?.cycle_name?.trim() || t.currentCycle;

  const toggleCard = (card) => {
    const nextCard = expandedCard === card ? null : card;
    setExpandedCard(nextCard);
    onExpandedCardChange?.(nextCard);
  };

  const budgetDetails = (
    <div className="editorial-detail-grid editorial-budget-details">
      <dl>
        <div><dt>{t.cycleIncome}</dt><dd>EGP {money(currentCycle?.income_amount, language)}</dd></div>
        <div><dt>{t.totalSpent}</dt><dd>EGP {money(analysis?.total_spent, language)}</dd></div>
        <div><dt>{t.remaining}</dt><dd>EGP {money(budgetData?.remaining_total_budget, language)}</dd></div>
        <div><dt>{t.remainingDays}</dt><dd>{budgetData?.remaining_days || 0}</dd></div>
      </dl>
      <p>{t.budgetNote}</p>
      <button className="editorial-text-action" type="button" onClick={onOpenBudget}>{t.viewAll} <Arrow size={18} /></button>
    </div>
  );

  const spentDetails = (
    <div className="editorial-spent-details">
      <span className="editorial-detail-kicker editorial-cycle-heading" title={selectedCycleHeading}>
        {selectedCycleHeading}
      </span>
      {spendingCategories.length === 0 ? <p>{t.noSpending}</p> : (
        <div className="editorial-spending-visualization">
          <div
            className="editorial-spending-bar"
            role="list"
            aria-label={`${selectedCycleHeading} spending by category`}
          >
            {spendingBreakdown.map((item, index) => {
              const position = index % 2 === 0 ? "above" : "below";
              return (
                <div
                  className={`editorial-spending-segment is-${position} ${index === 0 ? "is-first" : ""} ${index === spendingBreakdown.length - 1 ? "is-last" : ""}`}
                  key={item.isOther ? "other-spending" : item.category}
                  role="listitem"
                  aria-label={amountsHidden
                    ? `${item.category}: ${item.displayedPercentage}%, amount hidden`
                    : `${item.category}: ${item.displayedPercentage}%, EGP ${money(item.amount, language)}`}
                  style={{
                    "--segment-color": item.color,
                    width: `${item.percentage}%`,
                  }}
                >
                  <i className="editorial-spending-callout-line" aria-hidden="true" />
                  <div className="editorial-spending-callout" aria-hidden="true">
                    <span title={item.category}>{item.category}</span>
                    <strong>{item.displayedPercentage}%</strong>
                    <small>EGP {money(item.amount, language)}</small>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <span className="editorial-detail-kicker">{t.recent}</span>
      <div className="editorial-transaction-list">
        {recentExpenses.length > 0 ? recentExpenses.slice(0, 4).map((expense) => (
          <div key={expense.id}>
            <span><strong>{expense.subcategory_name || expense.category_name}</strong><small>{shortDate(expense.expense_date, language)}</small></span>
            <b>EGP {money(expense.amount, language)}</b>
          </div>
        )) : paceDays.slice(-3).reverse().map((day) => (
          <div key={day.date}>
            <span><strong>{t.recentDays}</strong><small>{shortDate(day.date, language)}</small></span>
            <b>EGP {money(day.used_today, language)}</b>
          </div>
        ))}
      </div>
      <button className="editorial-text-action" type="button" onClick={onOpenSpending}>{t.viewSpending} <Arrow size={18} /></button>
    </div>
  );

  const goalsDetails = (
    <div className="editorial-goal-list">
      {activeGoals.length === 0 ? <p>{t.noGoals}</p> : activeGoals.slice(0, 4).map((goal) => {
        const progress = Math.min(100, Math.round((Number(goal.current_amount || 0) / Math.max(Number(goal.target_amount || 0), 1)) * 100));
        return (
          <div key={goal.id}>
            <span><strong>{goal.name}</strong><small>EGP {money(goal.current_amount, language)} {t.saved}</small></span>
            <b>{progress}%</b><i><em style={{ width: `${progress}%` }} /></i>
          </div>
        );
      })}
      <button className="editorial-text-action" type="button" onClick={onOpenGoals}>{t.viewAll} <Arrow size={18} /></button>
    </div>
  );

  const creditDetails = (
    <div className="editorial-credit-list">
      {outstandingExpenses.length === 0 ? <p>{t.noCredit}</p> : outstandingExpenses.slice(0, 5).map((expense) => (
        <div key={expense.id}>
          <span><strong>{expense.subcategory || expense.category}</strong><small>{shortDate(expense.expense_date, language)} · {t.outstanding}</small></span>
          <b>EGP {money(expense.amount, language)}</b>
        </div>
      ))}
      <button className="editorial-text-action" type="button" onClick={onOpenCard}>{t.manageCards} <Arrow size={18} /></button>
    </div>
  );

  return (
    <main className={`editorial-dashboard pulse-dashboard ${amountsHidden ? "amounts-hidden" : ""}`} dir={isArabic ? "rtl" : "ltr"}>
      <div className="editorial-dashboard-content">
        <div className="editorial-hero-composition">
          <aside className="editorial-identity-rail" role="img" aria-label={railCalendarLabel}>
            <div className="editorial-rail-body" aria-hidden="true">
              <strong className={`editorial-rail-weekday ${!isArabic && railWeekday.length >= 9 ? "is-long" : ""}`} lang={isArabic ? "ar" : "en"}>{railWeekday}</strong>
              <span className="editorial-rail-divider" />
              <div className="editorial-rail-date">
                <small>{t.railDay}</small>
                <b>{railDate.day}</b>
              </div>
            </div>
            <em className="editorial-rail-month" aria-hidden="true" lang={isArabic ? "ar" : "en"}>{railDate.month}</em>
          </aside>
        <section className="editorial-hero">
          <div className="editorial-greeting"><span>{t.hi}, {userName}</span><div>
            <button type="button" onClick={onOpenSettings} aria-label="Open settings"><Settings size={22} /></button>
            <button type="button" onClick={onLogout} aria-label="Logout"><LogOut size={20} /></button>
          </div></div>
          <div className="editorial-privacy-control">
            <button
              className="editorial-privacy-switch"
              type="button"
              role="switch"
              aria-checked={amountsHidden}
              onClick={() => onAmountsHiddenChange?.(!amountsHidden)}
            >
              <span>{amountsHidden ? t.showAmounts : t.hideAmounts}</span>
              <i aria-hidden="true"><b /></i>
            </button>
          </div>
          <span className="editorial-kicker">{t.safe}</span>
          <PulseFinancialValue
            className="editorial-safe-value editorial-private-value"
            amount={new Intl.NumberFormat(isArabic ? "ar-EG" : "en-US", {
              minimumFractionDigits: 2, maximumFractionDigits: 2,
            }).format(safeDailyAllowance)}
          />
          <div className={`editorial-safe-status ${needsBudgetWarning ? "is-alert" : ""}`}><span>— {budgetData?.remaining_days || 0} {t.daysLeft}</span><i /><span>{budgetStatus}</span>{today && <span className="editorial-private-value">{percentageLabel} {isArabic ? "متبقي اليوم" : "left today"}</span>}</div>
        </section>
        </div>

        <button className="editorial-action-strip editorial-ask-strip" type="button" onClick={onOpenAsk}><strong>{t.ask}</strong><span>{t.askText}</span><Arrow size={32} /></button>
        <button className="editorial-action-strip editorial-record-strip pulse-black-action" type="button" onClick={onRecordSpending}><span>{t.record}</span><Arrow className="pulse-black-action-arrow" size={20} /></button>

        <section className="editorial-glance" aria-labelledby="money-at-glance">
          <h2 id="money-at-glance">{t.glance}</h2>
          <div className="editorial-glance-grid">
            <MetricSlot id="budget" expanded={expandedCard === "budget"} details={budgetDetails}>
              <MetricCard id="budget" label={t.budget} amount={money(budgetData?.remaining_total_budget, language)} expanded={expandedCard === "budget"} onToggle={toggleCard} />
            </MetricSlot>
            <MetricSlot id="spent" expanded={expandedCard === "spent"} details={spentDetails}>
              <MetricCard id="spent" label={t.spent} amount={money(analysis?.total_spent, language)} expanded={expandedCard === "spent"} onToggle={toggleCard} />
            </MetricSlot>
            <MetricSlot id="goals" expanded={expandedCard === "goals"} details={goalsDetails}>
              <MetricCard id="goals" label={t.goals} value={`${activeGoals.length} ${t.active}`} meta={activeGoals[0]?.name} expanded={expandedCard === "goals"} onToggle={toggleCard} />
            </MetricSlot>
            <MetricSlot id="credit" expanded={expandedCard === "credit"} details={creditDetails}>
              <MetricCard id="credit" label={t.credit} amount={money(paymentSummary?.outstanding_credit_card, language)} meta={`${paymentSummary?.outstanding_count || 0} ${t.purchases}`} expanded={expandedCard === "credit"} onToggle={toggleCard} />
            </MetricSlot>
          </div>
        </section>

        <section className={`editorial-daily-pace ${expandedCard === "pace" ? "is-expanded" : ""}`}>
          <button type="button" className="editorial-pace-toggle" aria-expanded={expandedCard === "pace"} aria-controls="editorial-pace-details" onClick={() => toggleCard("pace")}>
            <span>{t.pace}</span><div aria-hidden="true">{paceDays.map((day) => <i key={day.date} className={day.date === selectedPaceDay?.date ? "is-active" : ""} style={{ height: `${Math.max(14, (Number(day.used_today || 0) / maxPaceValue) * 100)}%` }} />)}</div>
            <small>{budgetStatus}</small><Arrow size={22} />
          </button>
          <div className="editorial-pace-details" id="editorial-pace-details">
            <div className="editorial-pace-details-inner">
              <PulseCalendar
                days={dailyTable}
                selectedDate={selectedPaceDay?.date}
                language={language}
                tone="dark"
                amountsHidden={amountsHidden}
                onSelect={(day) => setPaceIndex(actualDays.findIndex((item) => item.date === day.date))}
              />
              {selectedPaceDay && <div className="editorial-selected-day">
                <span><small>{t.selectedDay}</small><strong>{shortDate(selectedPaceDay.date, language)}</strong></span>
                <span><small>{t.allowance}</small><strong>EGP {money(selectedPaceDay.available_today, language)}</strong></span>
                <span><small>{t.used}</small><strong>EGP {money(selectedPaceDay.used_today, language)}</strong></span>
                <span><small>{t.left}</small><strong>EGP {money(selectedPaceDay.remaining_today, language)}</strong></span>
              </div>}
              {selectedPaceDay && <button className="editorial-pace-open pulse-black-action" type="button" onClick={() => onOpenDay?.(selectedPaceDay)}><span>{t.openDay}</span><Arrow className="pulse-black-action-arrow" size={18} /></button>}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

export default ModernDashboard;
