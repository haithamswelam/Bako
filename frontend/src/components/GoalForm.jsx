const goalTypes = [
  ["required_bill", "Required bill"],
  ["savings", "Savings"],
  ["charity", "Charity"],
  ["lifestyle", "Lifestyle"],
  ["event", "Event"],
  ["debt", "Debt"]
];

function GoalForm({
  values,
  onChange,
  onSubmit,
  onDelete,
  loading,
  submitLabel = "Create Goal"
}) {
  const setValue = (field) => (event) => {
    onChange(field, event.target.value);
  };
  const isValid = Boolean(
    values.name.trim() &&
    Number(values.targetAmount) > 0 &&
    Number(values.currentAmount || 0) >= 0
  );

  return (
    <form
      className="goal-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label>
        <span>Goal name</span>
        <input
          value={values.name}
          onChange={setValue("name")}
          placeholder="Building Maintenance"
          required
        />
      </label>

      <div className="goal-form-grid">
        <label>
          <span>Type</span>
          <select value={values.type} onChange={setValue("type")}>
            {goalTypes.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>

        <label>
          <span>Priority</span>
          <select value={values.priority} onChange={setValue("priority")}>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </label>
      </div>

      <div className="goal-form-grid">
        <label>
          <span>Target amount</span>
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={values.targetAmount}
            onChange={setValue("targetAmount")}
            required
          />
        </label>

        <label>
          <span>Current amount</span>
          <input
            type="number"
            min="0"
            step="0.01"
            value={values.currentAmount}
            onChange={setValue("currentAmount")}
          />
        </label>
      </div>

      <label>
        <span>Deadline date</span>
        <input
          type="date"
          value={values.deadlineDate}
          onChange={setValue("deadlineDate")}
        />
      </label>

      <label>
        <span>Auto rule (optional)</span>
        <input
          value={values.autoRule}
          onChange={setValue("autoRule")}
          placeholder="2.5_percent_of_daily_budget"
        />
      </label>

      <button className="primary-button pulse-button pulse-button-accent" type="submit" disabled={loading || !isValid}>
        {loading ? "Saving goal..." : submitLabel}
      </button>
      {onDelete && (
        <button className="pulse-button pulse-button-secondary" type="button" disabled={loading} onClick={onDelete}>
          Delete goal
        </button>
      )}
    </form>
  );
}

export default GoalForm;
