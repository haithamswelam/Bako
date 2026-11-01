import { useCallback, useEffect, useRef, useState } from "react";

import SpendingAnalysis from "./components/SpendingAnalysis";
import ModernDashboard from "./components/ModernDashboard";
import AIConversationHistory from "./components/AIConversationHistory";
import { formatSubcategoryName } from "./utils/displayNames";
import { VERIFIED_QURAN_VERSE } from "./data/verifiedQuranVerse";


import {
  ChevronLeft,
  ChevronRight,
  Plus,
  Settings,
  LogOut
} from "lucide-react";

import {
  createCycle,
  getCycles,
  getCycleSummary,
  getCycleComparison,
  updateCycle,
  addCycleBudget,
  deleteCycle,
  getCategories,
  getSubcategories,
  createCategory,
  createSubcategory,
  createCategoryPair,
  updateCategory,
  archiveCategory,
  updateSubcategory,
  archiveSubcategory,
  suggestExpenseCategory,
  getAnalysis,
  askAICoach,
  getAIChatHistory,
  getGoals,
  getPaymentSummary,
  getCreditCards,
  createCreditCard,
  getCreditCardExpenses,
  updateCreditCardSettlement,
  getBudgetData,
  createExpense,
  createGoal,
  updateGoal,
  deleteGoal,
  contributeToGoal,
  registerUser,
  loginUser,
  getCurrentUser,
  updateCurrentUser,
  saveToken,
  getToken,
  logout,
  saveCycleId,
  getCycleId,
  getCurrentCycle,
  getDailyDetails,
  updateExpense,
  deleteExpense,
  forgotPassword,
  resetPassword
} from "./services/api";

import ExpenseForm from "./components/ExpenseForm";
import Toast from "./components/Toast";
import Modal from "./components/Modal";
import CycleForm from "./components/CycleForm";
import GoalForm from "./components/GoalForm";

import "./App.css";
import "./Dashboard.css";
import "./pulse/pulse.css";
import { PulseConfirmDialog, PulseErrorState } from "./pulse/PulsePrimitives";
import PulseCalendar from "./pulse/PulseCalendar";
import { BakoAuthPage, QuranStartupPage } from "./pulse/PulseAuth";
import { BakoOnboarding } from "./pulse/BakoOnboarding";

const createInitialAIChatMessages = () => [
  {
    role: "assistant",
    headline: "Ask about your current cycle",
    text: (
      "I can explain your budget pace, spending categories, goals, " +
      "and card spending using verified Bako data."
    )
  }
];

const createEmptyAIUsage = () => ({
  tokensUsedToday: 0,
  dailyTokenLimit: 2000000,
  usagePercentage: 0
});

const normalizeAIUsage = (summary = {}) => ({
  tokensUsedToday: Number(summary.tokens_used_today) || 0,
  dailyTokenLimit: Number(summary.daily_token_limit) || 2000000,
  usagePercentage: Number(summary.usage_percentage) || 0
});

const validateAuthFields = ({ email, password = "", requirePassword = false }) => {
  const errors = {};
  const normalizedEmail = email.trim();

  if (!normalizedEmail) {
    errors.email = "Email is required.";
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
    errors.email = "Enter a valid email address.";
  }

  if (requirePassword && !password) {
    errors.password = "Password is required.";
  }

  return errors;
};

const getAuthFailureMessage = (error, fallback) => {
  if (error instanceof TypeError) {
    return "Bako is temporarily unavailable. Please try again.";
  }
  return error?.message || fallback;
};

const modernPageCopy = {
  en: {
    budget: ["Budget", "Your current cycle position"],
    spending: ["Where it went", "Spending by category"],
    goals: ["Goals", "Build savings without losing your budget pace"],
    card: ["Credit Card due", "Credit-card purchases and settlement"],
    pace: ["Daily pace", "Daily spending against your safe allowance"],
    ask: ["Ask Bako", "Clear answers about your money"],
    settings: ["Settings", "Profile, cycles and preferences"],
    record: ["Record spending", "Add and review daily expenses"],
    profileName: "Profile name",
    greetingHint: "Used in your greeting",
    currentCycle: "Current cycle",
    currency: "Currency",
    language: "Language",
    languageHint: "Choose the application language",
    aiUsage: "AI usage today",
    sharedWindow: "Shared provider daily window",
    financialCycles: "Financial cycles",
    createCycle: "Create cycle",
    noCycles: "No cycles yet.",
    selected: "Selected",
    previous: "Previous",
    use: "Use",
    summary: "Summary",
    editName: "Edit name",
    delete: "Delete",
    compareCycles: "Compare cycles",
    compareHint: "See what changed between two periods.",
    from: "From",
    to: "To",
    comparing: "Comparing...",
    safeToday: "Safe today",
    onTrack: "On track",
    selectedDay: "Selected day",
    allowed: "Allowed",
    usedLeft: "Used / left"
  },
  ar: {
    budget: ["الميزانية", "وضع ميزانيتك في الدورة الحالية"],
    spending: ["راحت فين", "المصروفات حسب التصنيف"],
    goals: ["الأهداف", "ادخر من غير ما تخسر توازن ميزانيتك"],
    card: ["مستحق البطاقة", "مشتريات البطاقة وحالة السداد"],
    pace: ["معدل الصرف", "صرفك اليومي مقارنة بالمبلغ الآمن"],
    ask: ["اسأل مصاريفي", "افهم فلوسك بمساعدة الذكاء الاصطناعي"],
    settings: ["الإعدادات", "الملف الشخصي والدورات والتفضيلات"],
    record: ["سجل مصروف", "أضف وراجع مصروفاتك اليومية"],
    profileName: "الاسم",
    greetingHint: "يظهر في التحية",
    currentCycle: "الدورة الحالية",
    currency: "العملة",
    language: "اللغة",
    languageHint: "اختر لغة التطبيق",
    aiUsage: "استخدام الذكاء الاصطناعي اليوم",
    sharedWindow: "الحد اليومي المشترك لمزود الخدمة",
    financialCycles: "الدورات المالية",
    createCycle: "دورة جديدة",
    noCycles: "لا توجد دورات حتى الآن.",
    selected: "المحددة",
    previous: "السابقة",
    use: "استخدم",
    summary: "الملخص",
    editName: "تعديل الاسم",
    delete: "حذف",
    compareCycles: "قارن الدورات",
    compareHint: "شاهد ما تغير بين فترتين.",
    from: "من",
    to: "إلى",
    comparing: "جارٍ المقارنة...",
    safeToday: "المتاح اليوم",
    onTrack: "الوضع جيد",
    selectedDay: "اليوم المحدد",
    allowed: "المتاح",
    usedLeft: "المستخدم / المتبقي"
  }
};

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(!!getToken());
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [isOnboardingMode, setIsOnboardingMode] = useState(false);
  const [authEmail, setAuthEmail] = useState("");
  const [authDisplayName, setAuthDisplayName] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authPasswordVisible, setAuthPasswordVisible] = useState(false);
  const [authFieldErrors, setAuthFieldErrors] = useState({});
  const [authStatus, setAuthStatus] = useState({ message: "", tone: "error" });
  const [loginVerseLoading, setLoginVerseLoading] = useState(false);
  const [forgotMode, setForgotMode] = useState(false);
  const [resetToken, setResetToken] = useState("");
  const [generatedToken, setGeneratedToken] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const [currentCycleId, setCurrentCycleId] = useState(getCycleId());
  const [currentCycle, setCurrentCycle] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [cycles, setCycles] = useState([]);
  const [cycleLoadStatus, setCycleLoadStatus] = useState(
    isAuthenticated ? "loading" : "idle"
  );
  const [cycleSummary, setCycleSummary] = useState(null);
  const [cycleComparison, setCycleComparison] = useState(null);
  const [isCycleComparisonModalOpen, setIsCycleComparisonModalOpen] =
    useState(false);
  const [comparisonBaseCycleId, setComparisonBaseCycleId] = useState("");
  const [comparisonTargetCycleId, setComparisonTargetCycleId] = useState("");
  const [cycleComparisonLoading, setCycleComparisonLoading] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [isCycleSummaryModalOpen, setIsCycleSummaryModalOpen] = useState(false);
  const [editingCycle, setEditingCycle] = useState(null);
  const [editingCycleName, setEditingCycleName] = useState("");
  const [cycleActionLoading, setCycleActionLoading] = useState(false);

  const [categories, setCategories] = useState([]);
  const [subcategories, setSubcategories] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedSubcategory, setSelectedSubcategory] = useState("");
  const [amount, setAmount] = useState("");
  const [expenseDescription, setExpenseDescription] = useState("");
  const [paymentChannel, setPaymentChannel] = useState("cash");

  const [cycleName, setCycleName] = useState("");
  const [income, setIncome] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [cycleLoading, setCycleLoading] = useState(false);

  const [paymentSummary, setPaymentSummary] = useState(null);
  const [creditCardExpenses, setCreditCardExpenses] = useState([]);
  const [creditCards, setCreditCards] = useState([]);
  const [selectedCreditCard, setSelectedCreditCard] = useState("");
  const [newCreditCardName, setNewCreditCardName] = useState("");
  const [budgetAddition, setBudgetAddition] = useState("");
  const [budgetAdditionLoading, setBudgetAdditionLoading] = useState(false);

  const [analysis, setAnalysis] = useState(null);
  const [budgetData, setBudgetData] = useState(null);
  const [dailyTable, setDailyTable] = useState([]);
  const [goals, setGoals] = useState([]);

  const [loading, setLoading] = useState(isAuthenticated);
  const [error, setError] = useState(null);

  const [expenseLoading, setExpenseLoading] = useState(false);
  const [toastMessage, setToastMessage] = useState("");
  const [toastType, setToastType] = useState("success");
  const [amountsHidden, setAmountsHidden] = useState(false);
  const [confirmationRequest, setConfirmationRequest] = useState(null);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isAIModalOpen, setIsAIModalOpen] = useState(false);
  const [aiQuestion, setAIQuestion] = useState("");
  const [aiChatLoading, setAIChatLoading] = useState(false);
  const [aiChatMessages, setAIChatMessages] = useState(
    createInitialAIChatMessages
  );
  const [aiHistoryExchanges, setAIHistoryExchanges] = useState([]);
  const [aiView, setAIView] = useState("chat");
  const [selectedAIHistoryId, setSelectedAIHistoryId] = useState(null);
  const [, setAIUsage] = useState(createEmptyAIUsage);
  const [selectedDay, setSelectedDay] = useState(null);
  const [dailyDetails, setDailyDetails] = useState([]);
  const [dailyGoalContributions, setDailyGoalContributions] = useState([]);
  const [dashboardRecentExpenses, setDashboardRecentExpenses] = useState([]);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [showDayExpenseForm, setShowDayExpenseForm] = useState(false);
  const [isCycleModalOpen, setIsCycleModalOpen] = useState(false);
  const [dashboardPanel, setDashboardPanel] = useState(null);
  const [paceSelectedDate, setPaceSelectedDate] = useState(null);
  const [isGoalModalOpen, setIsGoalModalOpen] = useState(false);
  const [dayDetailsDirection, setDayDetailsDirection] = useState("next");
  const [dayDetailsDragOffset, setDayDetailsDragOffset] = useState(0);
  const [isDayDetailsDragging, setIsDayDetailsDragging] = useState(false);
  const [aiActionLoading, setAIActionLoading] = useState(false);
  const [goalLoading, setGoalLoading] = useState(false);
  const [editingGoal, setEditingGoal] = useState(null);
  const [contributionGoal, setContributionGoal] = useState(null);
  const [contributionAmount, setContributionAmount] = useState("");
  const [goalForm, setGoalForm] = useState({
    name: "",
    type: "savings",
    targetAmount: "",
    currentAmount: "",
    deadlineDate: "",
    priority: "medium",
    autoRule: ""
  });

  const requestConfirmation = (options) => new Promise((resolve) => {
    setConfirmationRequest({
      ...(typeof options === "string" ? { message: options } : options),
      resolve
    });
  });

  const resolveConfirmation = (confirmed) => {
    const pendingRequest = confirmationRequest;
    setConfirmationRequest(null);
    pendingRequest?.resolve(Boolean(confirmed));
  };

  const [editingExpense, setEditingExpense] = useState(null);
  const [editAmount, setEditAmount] = useState("");
  const [editPaymentChannel, setEditPaymentChannel] = useState("cash");
  const [editCreditCard, setEditCreditCard] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editSubcategory, setEditSubcategory] = useState("");
  const [editSubcategories, setEditSubcategories] = useState([]);
  const [editCategoryName, setEditCategoryName] = useState("");
  const [editSubcategoryName, setEditSubcategoryName] = useState("");
  const [showEditCreditCardCreate, setShowEditCreditCardCreate] = useState(false);
  const dayDetailsDragRef = useRef({
    startX: 0,
    pointerId: null,
    width: 1
  });
  const paceWeekSwipeRef = useRef({
    startX: 0,
    pointerId: null,
    didSwipe: false
  });

  const isCarouselInteractiveTarget = (target) =>
    Boolean(
      target?.closest?.(
        "button, input, select, textarea, a, label, .expense-form, .edit-expense-box, .expense-list, .modal-stats"
      )
    );

  const showToast = (message, type = "success") => {
    setToastMessage(message);
    setToastType(type);

    setTimeout(() => {
      setToastMessage("");
    }, 3000);
  };

  const handleAskAICoach = async (event, suggestedQuestion = null) => {
    event?.preventDefault?.();
    const question = (suggestedQuestion || aiQuestion).trim();

    if (!question || aiChatLoading) return;
    if (!currentCycleId) {
      showToast("Select a financial cycle before asking AI Coach.", "error");
      return;
    }

    setAIChatMessages((messages) => [
      ...messages,
      { role: "user", text: question }
    ]);
    setAIQuestion("");
    setAIChatLoading(true);

    try {
      const response = await askAICoach(currentCycleId, question, 5);
      const answer = response.explanation || {};
      setAIUsage(normalizeAIUsage(response.usage_summary));

      setAIChatMessages((messages) => [
        ...messages,
        {
          id: response.exchange_id
            ? `answer-${response.exchange_id}`
            : undefined,
          role: "assistant",
          headline: answer.headline || "Bako AI Coach",
          text: answer.explanation || "I could not prepare an explanation.",
          action: answer.recommended_action || null,
          topics: response.question_plan?.topics || [],
          actions: response.suggested_actions || [],
          source: answer.source || "deterministic_fallback"
        }
      ]);
      if (response.exchange_id) {
        setAIHistoryExchanges((exchanges) => [{
          id: response.exchange_id,
          question,
          headline: answer.headline || "Bako AI Coach",
          explanation: answer.explanation || "I could not prepare an explanation.",
          recommended_action: answer.recommended_action || null,
          source: answer.source || "deterministic_fallback",
          topics: response.question_plan?.topics || [],
          created_at: new Date().toISOString(),
        }, ...exchanges.filter((exchange) => exchange.id !== response.exchange_id)]);
      }
    } catch (requestError) {
      setAIChatMessages((messages) => [
        ...messages,
        {
          role: "assistant",
          headline: "I could not answer yet",
          text: requestError.message || "Please try again in a moment.",
          isError: true
        }
      ]);
    } finally {
      setAIChatLoading(false);
    }
  };

  useEffect(() => {
    setAIQuestion("");
    setAIView("chat");
    setSelectedAIHistoryId(null);
    if (!isAuthenticated || !currentCycleId) {
      setAIChatMessages(createInitialAIChatMessages());
      setAIHistoryExchanges([]);
      setAIUsage(createEmptyAIUsage());
      return undefined;
    }

    let isActive = true;
    getAIChatHistory(currentCycleId)
      .then((response) => {
        if (!isActive) return;
        setAIHistoryExchanges(response.exchanges || []);
        setAIChatMessages(createInitialAIChatMessages());
        setAIUsage(normalizeAIUsage(response.usage_summary));
      })
      .catch((historyError) => {
        console.error("Could not load AI Coach history", historyError);
        if (isActive) {
          setAIChatMessages(createInitialAIChatMessages());
          setAIHistoryExchanges([]);
          setAIUsage(createEmptyAIUsage());
        }
      });

    return () => {
      isActive = false;
    };
  }, [isAuthenticated, currentCycleId]);

  useEffect(() => {

  const loadCurrentCycle = async () => {

    if (!isAuthenticated) return;

    try {
      setLoading(true);
      setCycleLoadStatus("loading");

      const [userResponse, cycleResponse] =
        await Promise.all([
          getCurrentUser(),
          getCurrentCycle()
        ]);

      let cyclesResponse = { cycles: [] };

      try {
        cyclesResponse = await getCycles();
      } catch (cycleError) {
        console.error(
          "Failed to load cycles",
          cycleError
        );
        setCycleLoadStatus("error");
        cyclesResponse = {
          cycles: cycleResponse.cycle ? [cycleResponse.cycle] : []
        };
      }

      setCurrentUser(userResponse.user || userResponse);
      const loadedCycles = cyclesResponse.cycles || [];
      setCycles(loadedCycles);

      const selectedCycle =
        loadedCycles.find(
          (cycle) => String(cycle.id) === String(currentCycleId)
        ) ||
        cycleResponse.cycle ||
        loadedCycles[0];

      if (selectedCycle) {
        setCurrentCycle(
          selectedCycle
        );

        if (!loadedCycles.length && cycleResponse.cycle) {
          setCycles([cycleResponse.cycle]);
        }

        saveCycleId(
          selectedCycle.id
        );

        setCurrentCycleId(
          selectedCycle.id
        );
      } else {
        setCurrentCycle(null);
        setCurrentCycleId(null);
        saveCycleId(null);
      }

      setCycleLoadStatus("ready");
    } catch (error) {

      console.error(
        "Failed to load current cycle",
        error
      );
      setCycleLoadStatus("error");
    } finally {
      setLoading(false);
    }
  };

  loadCurrentCycle();

}, [isAuthenticated, currentCycleId]);

  const handleRegister = async () => {
    const fieldErrors = validateAuthFields({
      email: authEmail,
      password: authPassword,
      requirePassword: true
    });
    setAuthFieldErrors(fieldErrors);
    setAuthStatus({ message: "", tone: "error" });
    if (Object.keys(fieldErrors).length > 0) return;

    try {
      setAuthLoading(true);

      const response = await registerUser({
        email: authEmail,
        password: authPassword,
        display_name: authDisplayName.trim() || null
      });

      if (response.detail || response.error) {
        setAuthStatus({
          message: response.detail || response.error,
          tone: "error"
        });
        return;
      }

      setAuthStatus({ message: "Account created. You can now log in.", tone: "success" });
      setIsRegisterMode(false);
    } catch (error) {
      console.error(error);
      setAuthStatus({
        message: getAuthFailureMessage(error, "Registration failed."),
        tone: "error"
      });
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogin = async () => {
    const fieldErrors = validateAuthFields({
      email: authEmail,
      password: authPassword,
      requirePassword: true
    });
    setAuthFieldErrors(fieldErrors);
    setAuthStatus({ message: "", tone: "error" });
    if (Object.keys(fieldErrors).length > 0) return;

    try {
      setAuthLoading(true);

      const response = await loginUser({
        email: authEmail,
        password: authPassword
      });

      if (!response.access_token) {
        setAuthStatus({ message: "Incorrect email or password.", tone: "error" });
        return;
      }

      saveToken(response.access_token);
      setLoginVerseLoading(true);
    } catch (error) {
      console.error(error);
      setAuthStatus({
        message: getAuthFailureMessage(error, "Login failed."),
        tone: "error"
      });
    } finally {
      setAuthLoading(false);
    }
  };

  const handleForgotPassword = async () => {
    const fieldErrors = validateAuthFields({ email: authEmail });
    setAuthFieldErrors(fieldErrors);
    setAuthStatus({ message: "", tone: "error" });
    if (Object.keys(fieldErrors).length > 0) return;

    try {
      setAuthLoading(true);
      const response = await forgotPassword(authEmail);

      if (response.reset_token) {
        setGeneratedToken(response.reset_token);
        setAuthStatus({ message: "Reset token generated.", tone: "success" });
      }
    } catch (error) {
      console.error(error);
      setAuthStatus({
        message: getAuthFailureMessage(error, "Could not generate a reset token."),
        tone: "error"
      });
    } finally {
      setAuthLoading(false);
    }
  };

  const handleResetPassword = async () => {
    const fieldErrors = {};
    if (!resetToken.trim()) fieldErrors.resetToken = "Reset token is required.";
    if (!newPassword) fieldErrors.newPassword = "New password is required.";
    setAuthFieldErrors(fieldErrors);
    setAuthStatus({ message: "", tone: "error" });
    if (Object.keys(fieldErrors).length > 0) return;

    try {
      setAuthLoading(true);
      const response = await resetPassword(resetToken, newPassword);

      if (response.message === "Password reset successfully") {
        setAuthStatus({ message: "Password updated. You can now log in.", tone: "success" });
        setForgotMode(false);
        setGeneratedToken("");
        setResetToken("");
        setNewPassword("");
      }
    } catch (error) {
      console.error(error);
      setAuthStatus({
        message: getAuthFailureMessage(error, "Password reset failed."),
        tone: "error"
      });
    } finally {
      setAuthLoading(false);
    }
  };

  const finishLoginVerse = useCallback(() => {
    setLoginVerseLoading(false);
    setIsAuthenticated(true);
  }, []);

  const clearAuthFieldError = (fieldName) => {
    setAuthFieldErrors((errors) => {
      if (!errors[fieldName]) return errors;
      const nextErrors = { ...errors };
      delete nextErrors[fieldName];
      return nextErrors;
    });
    setAuthStatus({ message: "", tone: "error" });
  };

  const showLoginMode = () => {
    setForgotMode(false);
    setIsRegisterMode(false);
    setIsOnboardingMode(false);
    setGeneratedToken("");
    setAuthFieldErrors({});
    setAuthStatus({ message: "", tone: "error" });
  };

  const handleLogout = () => {
    logout();
    setIsAuthenticated(false);
    window.location.reload();
  };

  const handleLanguageChange = async (preferredLanguage) => {
    try {
      const profile = await updateCurrentUser({
        display_name: currentUser?.display_name || null,
        preferred_language: preferredLanguage
      });
      setCurrentUser(profile.user || profile);
    } catch (profileError) {
      console.error(profileError);
      showToast("Could not update language", "error");
    }
  };

  const handleCardSettlement = async (expense) => {
    try {
      await updateCreditCardSettlement(expense.id, !expense.settled_at);
      await refreshDashboard(currentCycleId);
      showToast(expense.settled_at ? "Card purchase reopened" : "Card purchase settled");
    } catch (settlementError) {
      console.error(settlementError);
      showToast("Could not update card settlement", "error");
    }
  };

  const handleAddBudget = async () => {
    const amountToAdd = Number(budgetAddition);
    if (!currentCycleId || !Number.isFinite(amountToAdd) || amountToAdd <= 0) {
      showToast("Enter a valid amount to add", "error");
      return;
    }
    try {
      setBudgetAdditionLoading(true);
      const response = await addCycleBudget(currentCycleId, amountToAdd);
      setCurrentCycle(response.cycle);
      setCycles((items) => items.map((cycle) => (
        String(cycle.id) === String(currentCycleId) ? response.cycle : cycle
      )));
      setBudgetAddition("");
      await refreshDashboard(currentCycleId);
      showToast("Budget added to this cycle");
    } catch (budgetError) {
      console.error(budgetError);
      showToast(budgetError.message || "Could not add budget", "error");
    } finally {
      setBudgetAdditionLoading(false);
    }
  };

  const handleCreateCreditCard = async () => {
    const name = newCreditCardName.trim();
    if (!name) {
      showToast("Enter a card name", "error");
      return;
    }
    try {
      const created = await createCreditCard(name.trim());
      setCreditCards((cards) => [
        ...cards.filter((card) => card.id !== created.id),
        created
      ].sort((left, right) => left.name.localeCompare(right.name)));
      setSelectedCreditCard(String(created.id));
      setNewCreditCardName("");
      showToast("Credit card added");
      return created;
    } catch (cardError) {
      showToast(cardError.message || "Could not add card", "error");
      return null;
    }
  };

  const refreshDashboard = useCallback(async (cycleId = currentCycleId) => {
    if (!cycleId) {
      setGoals([]);
      setAnalysis(null);
      setBudgetData(null);
      setDailyTable([]);
      setPaymentSummary(null);
      setCreditCardExpenses([]);
      setCreditCards([]);
      return;
    };

    const [
  analysisData,
  budgetResponse,
  paymentData,
  creditCardData,
  goalsResponse,
  cardsResponse
] = await Promise.all([
  getAnalysis(cycleId),
  getBudgetData(cycleId),
  getPaymentSummary(cycleId).catch((error) => {
    console.warn("Payment summary is not available yet", error);
    return {
      total_credit_card: 0,
      outstanding_credit_card: 0,
      settled_credit_card: 0,
      outstanding_count: 0
    };
  }),
  getCreditCardExpenses(cycleId).catch((error) => {
    console.warn("Credit card expenses are not available yet", error);
    return { expenses: [] };
  }),
  getGoals(false, cycleId).catch((error) => {
    console.error("Failed to load goals", error);
    return { goals: [] };
  }),
  getCreditCards().catch(() => ({ credit_cards: [] }))
]);

    setAnalysis(analysisData);
    setBudgetData(budgetResponse);
    setGoals(goalsResponse.goals || []);
    setDailyTable(budgetResponse.daily_table || []);
    setPaymentSummary(paymentData);
    setCreditCardExpenses(creditCardData.expenses || []);
    setCreditCards(cardsResponse.credit_cards || []);

    return budgetResponse;
  }, [currentCycleId]);

  const loadDayDetails = async (dayDate) => {
    if (!currentCycleId) return;

    try {
      setDetailsLoading(true);

      const response = await getDailyDetails(
        currentCycleId,
        dayDate
      );

      setDailyDetails(response.expenses || []);
      setDailyGoalContributions(response.goal_contributions || []);
    } catch (error) {
      console.error(error);
      setDailyDetails([]);
      setDailyGoalContributions([]);
      showToast("Could not load daily expenses", "error");
    } finally {
      setDetailsLoading(false);
    }
  };

  const handleEditorialCardChange = async (card) => {
    if (
      card !== "spent" ||
      !currentCycleId ||
      dashboardRecentExpenses.length > 0
    ) {
      return;
    }

    const recentDates = [...dailyTable]
      .filter((day) => day.status !== "future")
      .sort((a, b) => new Date(b.date) - new Date(a.date))
      .slice(0, 7)
      .map((day) => day.date);

    try {
      const responses = await Promise.all(
        recentDates.map((date) => getDailyDetails(currentCycleId, date))
      );
      const expenses = responses
        .flatMap((response) => response.expenses || [])
        .sort((a, b) => new Date(b.expense_date) - new Date(a.expense_date));

      setDashboardRecentExpenses(expenses.slice(0, 6));
    } catch (error) {
      console.error("Failed to load recent dashboard expenses", error);
    }
  };

  useEffect(() => {
    setDashboardRecentExpenses([]);
  }, [currentCycleId]);

  const refreshDashboardAndSelectedDay = async (
    cycleId = currentCycleId,
    dayDate = selectedDay?.date
  ) => {
    if (!cycleId) return;

    const budgetResponse = await refreshDashboard(cycleId);

    if (!dayDate) return;

    await loadDayDetails(dayDate);

    const updatedDay = (budgetResponse?.daily_table || []).find(
      (day) => day.date === dayDate
    );

    if (updatedDay) {
      setSelectedDay(updatedDay);
    }
  };


  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }

    getCategories().then((data) => setCategories(data));

    Promise.resolve(currentCycleId)
      .then((cycleId) => refreshDashboard(cycleId))
      .then(() => {
        setLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setError("Could not load dashboard.");
        setLoading(false);
      });
  }, [
    isAuthenticated,
    currentCycleId,
    refreshDashboard
  ]);

  useEffect(() => {
    if (!selectedCategory) return;

    let isActive = true;

    getSubcategories(selectedCategory).then((data) => {
      if (isActive) {
        setSubcategories(data);
      }
    });

    return () => {
      isActive = false;
    };
  }, [selectedCategory]);

  const handleCategoryChange = (categoryId) => {
    setSelectedCategory(categoryId);
    setSelectedSubcategory("");
    setSubcategories([]);
  };

  const handleCreateCategory = async (name) => {
    const created = await createCategory(name);
    setCategories((current) => (
      [...current, created].sort((left, right) => (
        left.name.localeCompare(right.name)
      ))
    ));
    handleCategoryChange(String(created.id));
    showToast("Spending group added.");
    return created;
  };

  const handleCreateSubcategory = async (name) => {
    if (!selectedCategory) {
      throw new Error("Choose a spending group first");
    }
    const created = await createSubcategory(selectedCategory, name);
    setSubcategories((current) => (
      [...current, created].sort((left, right) => (
        left.name.localeCompare(right.name)
      ))
    ));
    setSelectedSubcategory(String(created.id));
    showToast("Expense type added.");
    return created;
  };

  const handleRenameCategory = async (categoryId, name) => {
    const updated = await updateCategory(categoryId, name);
    setCategories((current) => (
      current
        .map((category) => (
          category.id === updated.id ? updated : category
        ))
        .sort((left, right) => left.name.localeCompare(right.name))
    ));
    showToast("Spending group renamed.");
    return updated;
  };

  const handleArchiveCategory = async (categoryId) => {
    await archiveCategory(categoryId);
    setCategories((current) => current.filter(
      (category) => category.id !== Number(categoryId)
    ));
    handleCategoryChange("");
    showToast("Spending group removed from future expenses.");
  };

  const handleRenameSubcategory = async (subcategoryId, name) => {
    const updated = await updateSubcategory(subcategoryId, name);
    setSubcategories((current) => (
      current
        .map((subcategory) => (
          subcategory.id === updated.id ? updated : subcategory
        ))
        .sort((left, right) => left.name.localeCompare(right.name))
    ));
    showToast("Expense type renamed.");
    return updated;
  };

  const handleArchiveSubcategory = async (subcategoryId) => {
    await archiveSubcategory(subcategoryId);
    setSubcategories((current) => current.filter(
      (subcategory) => subcategory.id !== Number(subcategoryId)
    ));
    setSelectedSubcategory("");
    showToast("Expense type removed from future expenses.");
  };

  const handleStartEditExpense = async (expense) => {
    setEditingExpense(expense);
    setShowEditCreditCardCreate(false);
    setEditAmount(expense.amount);
    setEditPaymentChannel(expense.payment_channel || "cash");
    setEditCreditCard(expense.credit_card_id ? String(expense.credit_card_id) : "");
    setEditCategory(String(expense.category_id));
    setEditSubcategory(String(expense.subcategory_id));
    setEditCategoryName(expense.category_name || "");
    setEditSubcategoryName(expense.subcategory_name || "");

    try {
      const options = await getSubcategories(expense.category_id);
      setEditSubcategories(options);
    } catch (error) {
      console.error(error);
      setEditSubcategories([]);
      showToast("Could not load expense types", "error");
    }
  };

  const handleEditExpenseCategoryChange = async (categoryId) => {
    setEditCategory(categoryId);
    setEditSubcategory("");
    setEditSubcategoryName("");
    const category = categories.find(
      (item) => String(item.id) === String(categoryId)
    );
    setEditCategoryName(category?.name || "");

    if (!categoryId) {
      setEditSubcategories([]);
      return;
    }

    try {
      setEditSubcategories(await getSubcategories(categoryId));
    } catch (error) {
      console.error(error);
      setEditSubcategories([]);
      showToast("Could not load expense types", "error");
    }
  };

  const handleEditExpenseSubcategoryChange = (subcategoryId) => {
    setEditSubcategory(subcategoryId);
    const subcategory = editSubcategories.find(
      (item) => String(item.id) === String(subcategoryId)
    );
    setEditSubcategoryName(subcategory?.name || "");
  };

  const handleUpdateDailyExpense = async () => {
    if (!editCategory || !editSubcategory) {
      showToast("Choose where the money went and what kind", "error");
      return;
    }

    const categoryName = editCategoryName.trim();
    const subcategoryName = editSubcategoryName.trim();
    if (!categoryName || !subcategoryName) {
      showToast("Category and type names cannot be empty", "error");
      return;
    }

    try {
      const currentCategory = categories.find(
        (item) => String(item.id) === String(editCategory)
      );
      const currentSubcategory = editSubcategories.find(
        (item) => String(item.id) === String(editSubcategory)
      );

      if (currentCategory && currentCategory.name !== categoryName) {
        await handleRenameCategory(editCategory, categoryName);
      }
      if (currentSubcategory && currentSubcategory.name !== subcategoryName) {
        await handleRenameSubcategory(editSubcategory, subcategoryName);
      }

      await updateExpense(editingExpense.id, {
        amount: parseFloat(editAmount),
        category_id: Number(editCategory),
        subcategory_id: Number(editSubcategory),
        description: editingExpense.description || "",
        expense_date: editingExpense.expense_date,
        payment_channel: editPaymentChannel,
        credit_card_id: editPaymentChannel === "credit_card" && editCreditCard
          ? Number(editCreditCard)
          : null
      });

      await loadDayDetails(selectedDay.date);
      const updatedBudget = await getBudgetData(currentCycleId);
      const updatedTable = updatedBudget.daily_table || [];
      setDailyTable(updatedTable);
      setBudgetData(updatedBudget);

      const updatedDay = updatedTable.find(
        (day) => day.date === selectedDay.date
      );
      if (updatedDay) {
        setSelectedDay(updatedDay);
      }

      setAnalysis(await getAnalysis(currentCycleId));
      setPaymentSummary(await getPaymentSummary(currentCycleId));
      setEditingExpense(null);
      showToast("Expense updated");
    } catch (error) {
      console.error(error);
      showToast(error.message || "Update failed", "error");
    }
  };

  const handleSuggestExpenseCategory = async (description) => {
    const response = await suggestExpenseCategory(description);
    if (response.usage_summary) {
      setAIUsage(normalizeAIUsage(response.usage_summary));
    }
    return response;
  };

  const handleUseSuggestedCategoryPair = async (suggestion) => {
    const categoryId = String(suggestion.category_id);
    const subcategoryId = String(suggestion.subcategory_id);
    const availableSubcategories = await getSubcategories(categoryId);

    setSelectedCategory(categoryId);
    setSubcategories(availableSubcategories);
    if (availableSubcategories.some(
      (subcategory) => String(subcategory.id) === subcategoryId
    )) {
      setSelectedSubcategory(subcategoryId);
    }
  };

  const handleCreateSuggestedCategoryPair = async (proposal) => {
    const created = await createCategoryPair(
      proposal.category_name,
      proposal.subcategory_name
    );
    setCategories((current) => (
      [
        ...current.filter((item) => item.id !== created.category.id),
        created.category
      ].sort((left, right) => left.name.localeCompare(right.name))
    ));
    const availableSubcategories = await getSubcategories(created.category.id);
    setSelectedCategory(String(created.category.id));
    setSubcategories(availableSubcategories);
    setSelectedSubcategory(String(created.subcategory.id));
    showToast("Suggested spending group and type added.");
    return created;
  };

  const handleSubmit = async ({ categorizationSuggestionId = null } = {}) => {
    if (!currentCycleId) {
      showToast("Please create a financial cycle first.", "error");
      setIsCycleModalOpen(true);
      return;
    }

    if (!selectedDay) {
      showToast("Choose a calendar day first.", "error");
      return;
    }

    try {
      setExpenseLoading(true);

      await createExpense({
        amount: parseFloat(amount),
        category_id: parseInt(selectedCategory),
        subcategory_id: parseInt(selectedSubcategory),
        cycle_id: parseInt(currentCycleId),
        description: expenseDescription.trim(),
        expense_date: selectedDay.date,
        payment_channel: paymentChannel,
        credit_card_id: paymentChannel === "credit_card" && selectedCreditCard
          ? Number(selectedCreditCard)
          : null,
        categorization_suggestion_id: categorizationSuggestionId
      });

      await refreshDashboardAndSelectedDay(currentCycleId, selectedDay.date);

      showToast("Expense added successfully!");

      setAmount("");
      setExpenseDescription("");
      setSelectedCategory("");
      setSelectedSubcategory("");
      setPaymentChannel("cash");
      setSelectedCreditCard("");
      setShowDayExpenseForm(false);
    } catch (error) {
      console.error(error);
      showToast("Failed to add expense", "error");
    } finally {
      setExpenseLoading(false);
    }
  };

  const handleCreateCycle = async () => {
    try {
      setCycleLoading(true);
      const newCycleName = cycleName.trim() || "Monthly Income";

      const response = await createCycle({
        cycle_name: newCycleName,
        income_amount: parseFloat(income),
        start_date: startDate,
        end_date: endDate
      });

      const createdCycle = {
        id: response.cycle_id,
        cycle_name: newCycleName,
        income_amount: parseFloat(income),
        start_date: startDate,
        end_date: endDate,
        status: "active"
      };

      setCurrentCycle(createdCycle);
      setCycles((current) => [
        createdCycle,
        ...current.filter((cycle) => cycle.id !== response.cycle_id)
      ]);
      setCycleLoadStatus("ready");
      saveCycleId(response.cycle_id);
      setCurrentCycleId(response.cycle_id);
      setGoals([]);

      showToast("Financial cycle created!");

      setCycleName("");
      setIncome("");
      setStartDate("");
      setEndDate("");

      await refreshDashboard(response.cycle_id);
      setIsCycleModalOpen(false);
    } catch (error) {
      console.error(error);
      showToast("Failed to create cycle", "error");
    } finally {
      setCycleLoading(false);
    }
  };

  const formatCycleDate = (value, options) =>
    new Date(`${value}T00:00:00`).toLocaleDateString("en-US", options);

  const shiftCycleMonth = (value, offset) => {
    const date = new Date(`${value}T00:00:00`);
    date.setMonth(date.getMonth() + offset);
    return [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0")
    ].join("-");
  };

  const cycleHistory = (() => {
    if (cycles.length > 1 || !currentCycle) return cycles;

    return [
      currentCycle,
      {
        id: `previous-${currentCycle.id}`,
        cycle_name: "Monthly Income",
        start_date: shiftCycleMonth(currentCycle.start_date, -1),
        end_date: shiftCycleMonth(currentCycle.end_date, -1),
        is_history_placeholder: true
      }
    ];
  })();

  const comparableCycles = cycleHistory.filter(
    (cycle) => !cycle.is_history_placeholder
  );
  const effectiveComparisonTargetCycleId =
    comparisonTargetCycleId || String(comparableCycles[0]?.id || "");
  const effectiveComparisonBaseCycleId =
    comparisonBaseCycleId || String(comparableCycles[1]?.id || "");

  const cycleMonthLabel =
    currentCycle?.start_date && currentCycle?.end_date
      ? `${formatCycleDate(currentCycle.start_date, {
          month: "short",
          day: "numeric"
        })} - ${formatCycleDate(currentCycle.end_date, {
          month: "short",
          day: "numeric",
          year: "numeric"
        })}`
      : "Cycle Calendar";

  const showCycleRecovery =
    !currentCycleId && cycleLoadStatus === "error";
  const showCyclePickerPrompt =
    !currentCycleId && cycleLoadStatus === "ready" && cycles.length > 0;
  const showCycleLoadingPrompt =
    !currentCycleId && (cycleLoadStatus === "loading" || cycleLoadStatus === "idle");
  const showNewUserPrompt =
    !currentCycleId && cycleLoadStatus === "ready" && cycles.length === 0;
  const isDashboardBootstrapping =
    isAuthenticated &&
    (
      loading ||
      cycleLoadStatus === "loading" ||
      cycleLoadStatus === "idle"
    );

  const now = new Date();
  const todayKey = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0")
  ].join("-");

  const todayBudget = dailyTable.find((day) => day.date === todayKey);
  const uiLanguage = currentUser?.preferred_language === "ar" ? "ar" : "en";
  const isArabicUI = uiLanguage === "ar";
  const pageText = modernPageCopy[uiLanguage];
  const userDisplayName =
    currentUser?.display_name ||
    currentUser?.name ||
    currentUser?.email?.split("@")[0]?.replace(/[._-]+/g, " ") ||
    "Bako";
  const cycleDays = [...dailyTable].sort(
    (a, b) => new Date(a.date) - new Date(b.date)
  );
  const latestPaceDayIndex = cycleDays.reduce(
    (latestIndex, day, index) => (
      day.status !== "future" && day.date <= todayKey ? index : latestIndex
    ),
    -1
  );
  const defaultPaceDayIndex = latestPaceDayIndex >= 0
    ? latestPaceDayIndex
    : Math.max(cycleDays.length - 1, 0);
  const requestedPaceDayIndex = paceSelectedDate
    ? cycleDays.findIndex((day) => day.date === paceSelectedDate)
    : defaultPaceDayIndex;
  const paceDayIndex = requestedPaceDayIndex >= 0
    ? Math.min(requestedPaceDayIndex, defaultPaceDayIndex)
    : defaultPaceDayIndex;
  const paceSelectedDay = cycleDays[paceDayIndex] || todayBudget || null;
  const paceChartDays = cycleDays.slice(
    Math.max(0, paceDayIndex - 6),
    paceDayIndex + 1
  );
  const canShowPreviousPaceWeek = paceDayIndex > 0;
  const canShowNextPaceWeek = paceDayIndex < defaultPaceDayIndex;
  const maxPaceChartValue = Math.max(
    ...paceChartDays.map((day) => Number(day.used_today || 0)),
    1
  );
  const selectedDayIndex = selectedDay
    ? cycleDays.findIndex((day) => day.date === selectedDay.date)
    : -1;
  const canNavigatePrevious = selectedDayIndex > 0;
  const canNavigateNext =
    selectedDayIndex >= 0 && selectedDayIndex < cycleDays.length - 1;
  const dayDetailSlides = selectedDay
    ? [
        canNavigatePrevious ? cycleDays[selectedDayIndex - 1] : null,
        selectedDay,
        canNavigateNext ? cycleDays[selectedDayIndex + 1] : null
      ]
    : [];
  const selectedDayExpensesTotal = dailyDetails.reduce(
    (sum, expense) => sum + Number(expense.amount || 0),
    0
  );
  const selectedDayGoalContributionsTotal = dailyGoalContributions.reduce(
    (sum, contribution) => sum + Number(contribution.amount || 0),
    0
  );
  const selectedDayDailyExpenses = selectedDay
    ? selectedDay.daily_expenses_today ??
      (
        dailyDetails.length > 0
          ? selectedDayExpensesTotal
          : selectedDay.spent_today
      )
    : 0;
  const selectedDayGoalContributions = selectedDay
    ? selectedDay.goal_contributions_today ??
      selectedDayGoalContributionsTotal
    : 0;
  const selectedDayUsedToday = selectedDay
    ? selectedDay.used_today ??
      (
        selectedDayDailyExpenses +
        selectedDayGoalContributions
      )
    : 0;

  const navigateDayDetails = (offset) => {
    const nextDay = cycleDays[selectedDayIndex + offset];

    if (!nextDay) return;

    setDayDetailsDirection(offset > 0 ? "next" : "previous");
    setSelectedDay(nextDay);
    setDailyDetails([]);
    setDailyGoalContributions([]);
    setEditingExpense(null);
    setShowDayExpenseForm(false);
    loadDayDetails(nextDay.date);
  };

  const handleDayDetailsPointerDown = (event) => {
    if (!selectedDay || cycleDays.length <= 1) return;
    if (isCarouselInteractiveTarget(event.target)) return;

    const rect = event.currentTarget.getBoundingClientRect();
    dayDetailsDragRef.current = {
      startX: event.clientX,
      pointerId: event.pointerId,
      width: rect.width || 1
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setIsDayDetailsDragging(true);
    setDayDetailsDragOffset(0);
  };

  const handleDayDetailsPointerMove = (event) => {
    if (!isDayDetailsDragging) return;

    let distance = event.clientX - dayDetailsDragRef.current.startX;

    if (
      (distance > 0 && !canNavigatePrevious) ||
      (distance < 0 && !canNavigateNext)
    ) {
      distance *= 0.28;
    }

    setDayDetailsDragOffset(distance);
  };

  const finishDayDetailsDrag = (event) => {
    if (!isDayDetailsDragging) return;

    const distance = dayDetailsDragOffset;
    const threshold = Math.min(
      92,
      Math.max(48, dayDetailsDragRef.current.width * 0.18)
    );

    event.currentTarget.releasePointerCapture?.(
      dayDetailsDragRef.current.pointerId
    );

    setIsDayDetailsDragging(false);
    setDayDetailsDragOffset(0);

    if (Math.abs(distance) > threshold) {
      if (distance < 0 && canNavigateNext) {
        navigateDayDetails(1);
      } else if (distance > 0 && canNavigatePrevious) {
        navigateDayDetails(-1);
      }
    }
  };

  const shiftPaceWeek = (dayOffset) => {
    if (cycleDays.length === 0) return;

    const nextIndex = Math.min(
      defaultPaceDayIndex,
      Math.max(0, paceDayIndex + dayOffset)
    );

    setPaceSelectedDate(cycleDays[nextIndex]?.date || null);
  };

  const handlePaceWeekPointerDown = (event) => {
    paceWeekSwipeRef.current = {
      startX: event.clientX,
      pointerId: event.pointerId,
      didSwipe: false
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const handlePaceWeekPointerUp = (event) => {
    const distance = event.clientX - paceWeekSwipeRef.current.startX;

    event.currentTarget.releasePointerCapture?.(
      paceWeekSwipeRef.current.pointerId
    );

    if (distance > 44 && canShowPreviousPaceWeek) {
      paceWeekSwipeRef.current.didSwipe = true;
      shiftPaceWeek(-7);
    } else if (distance < -44 && canShowNextPaceWeek) {
      paceWeekSwipeRef.current.didSwipe = true;
      shiftPaceWeek(7);
    }
  };

  const openDayDetails = (day) => {
    if (!day) return;

    setDayDetailsDirection("next");
    setSelectedDay(day);
    setDailyDetails([]);
    setEditingExpense(null);
    setShowDayExpenseForm(false);
    setIsModalOpen(true);
    loadDayDetails(day.date);
  };

  const openTodayDetails = () => {
    const today =
      cycleDays.find((day) => day.date === todayKey) ||
      cycleDays.find((day) => day.date >= todayKey) ||
      cycleDays.at(-1);

    if (today) {
      openDayDetails(today);
    } else {
      showToast("Create a financial cycle first.", "error");
      setIsCycleModalOpen(true);
    }
  };

  const handleAIChatGoalAction = async (action, messageIndex) => {
    if (!action || !currentCycleId) return;

    try {
      setAIActionLoading(action.action_id);
      await contributeToGoal(
        action.goal_id,
        action.amount,
        parseInt(currentCycleId),
        todayKey
      );
      await refreshDashboardAndSelectedDay(currentCycleId, todayKey);
      setAIChatMessages((messages) => messages.map((message, index) => (
        index === messageIndex
          ? {
              ...message,
              actions: (message.actions || []).map((item) => (
                item.action_id === action.action_id
                  ? { ...item, applied: true }
                  : item
              ))
            }
          : message
      )));
      showToast("Goal updated and allowance refreshed");
    } catch (error) {
      console.error(error);
      showToast(error.message || "Goal contribution failed", "error");
    } finally {
      setAIActionLoading(false);
    }
  };

  const handleGoalFieldChange = (field, value) => {
    setGoalForm((current) => ({
      ...current,
      [field]: value
    }));
  };

  const resetGoalForm = () => {
    setGoalForm({
      name: "",
      type: "savings",
      targetAmount: "",
      currentAmount: "",
      deadlineDate: "",
      priority: "medium",
      autoRule: ""
    });
    setEditingGoal(null);
  };

  const openGoalModal = (goal = null) => {
    if (goal) {
      setEditingGoal(goal);
      setGoalForm({
        name: goal.name,
        type: goal.type,
        targetAmount: String(goal.target_amount),
        currentAmount: String(goal.current_amount),
        deadlineDate: goal.deadline_date || "",
        priority: goal.priority,
        autoRule: goal.auto_rule || ""
      });
    } else {
      resetGoalForm();
    }

    setIsGoalModalOpen(true);
  };

  const handleGoalSubmit = async () => {
    try {
      setGoalLoading(true);
      const payload = {
        cycle_id: currentCycleId ? parseInt(currentCycleId) : null,
        name: goalForm.name.trim(),
        type: goalForm.type,
        target_amount: parseFloat(goalForm.targetAmount),
        current_amount: parseFloat(goalForm.currentAmount || 0),
        deadline_date: goalForm.deadlineDate || null,
        priority: goalForm.priority,
        auto_rule: goalForm.autoRule.trim() || null,
        is_active: true
      };

      if (editingGoal) {
        await updateGoal(editingGoal.id, payload);
      } else {
        await createGoal(payload);
      }

      const wasEditingGoal = Boolean(editingGoal);
      resetGoalForm();
      setIsGoalModalOpen(false);
      await refreshDashboard(currentCycleId);
      showToast(wasEditingGoal ? "Goal updated" : "Goal created");
    } catch (error) {
      console.error(error);
      showToast(error.message || "Failed to save goal", "error");
    } finally {
      setGoalLoading(false);
    }
  };

  const handleDeleteGoal = async () => {
    if (!editingGoal || goalLoading) return;
    const goal = editingGoal;
    const confirmed = await requestConfirmation({
      title: "Delete this goal?",
      message: `Deleting "${goal.name}" permanently removes the goal and its recorded contributions. Budget balances will be recalculated. This cannot be undone.`,
      confirmLabel: "Delete goal"
    });
    if (!confirmed) return;

    try {
      setGoalLoading(true);
      await deleteGoal(goal.id);
      setIsGoalModalOpen(false);
      resetGoalForm();
      if (currentCycleId) await refreshDashboardAndSelectedDay(currentCycleId);
      else await refreshDashboard(currentCycleId);
      showToast("Goal deleted");
    } catch (error) {
      showToast(error.message || "Failed to delete goal", "error");
    } finally {
      setGoalLoading(false);
    }
  };

  const handleContributeToGoal = async () => {
    if (!contributionGoal) return;

    try {
      await contributeToGoal(
        contributionGoal.id,
        parseFloat(contributionAmount),
        currentCycleId ? parseInt(currentCycleId) : null,
        todayKey
      );
      setContributionGoal(null);
      setContributionAmount("");
      await refreshDashboardAndSelectedDay(currentCycleId, todayKey);
      showToast("Contribution added");
    } catch (error) {
      console.error(error);
      showToast(error.message || "Contribution failed", "error");
    }
  };

  const switchCycle = async (cycle) => {
    if (!cycle || cycle.is_history_placeholder) return;

    setCurrentCycle(cycle);
    setAnalysis(null);
    setBudgetData(null);
    setDailyTable([]);
    setDashboardRecentExpenses([]);
    setCycleLoadStatus("ready");
    saveCycleId(cycle.id);
    setCurrentCycleId(cycle.id);
    setIsSettingsModalOpen(false);

    try {
      await refreshDashboard(cycle.id);
      showToast(`Switched to ${cycle.cycle_name || "Monthly Income"}`);
    } catch (error) {
      console.error(error);
      showToast("Failed to switch cycle", "error");
    }
  };

  const openEditCycleModal = (cycle) => {
    setEditingCycle(cycle);
    setEditingCycleName(cycle.cycle_name || "Monthly Income");
  };

  const handleUpdateCycleName = async () => {
    if (!editingCycle) return;

    try {
      setCycleActionLoading(true);
      const response = await updateCycle(editingCycle.id, {
        cycle_name: editingCycleName.trim() || "Monthly Income"
      });
      const updatedCycle = response.cycle;

      setCycles((current) =>
        current.map((cycle) =>
          String(cycle.id) === String(updatedCycle.id)
            ? updatedCycle
            : cycle
        )
      );

      if (String(currentCycleId) === String(updatedCycle.id)) {
        setCurrentCycle(updatedCycle);
      }

      setEditingCycle(null);
      setEditingCycleName("");
      showToast("Cycle name updated");
    } catch (error) {
      console.error(error);
      showToast(error.message || "Failed to update cycle", "error");
    } finally {
      setCycleActionLoading(false);
    }
  };

  const handleDeleteCycle = async (cycle) => {
    if (!cycle || cycle.is_history_placeholder) return;

    const confirmed = await requestConfirmation({
      title: "Delete this cycle?",
      message: `Deleting "${cycle.cycle_name || "Monthly Income"}" permanently removes its spending and goal contributions.`,
      confirmLabel: "Delete cycle"
    });

    if (!confirmed) return;

    try {
      setCycleActionLoading(true);
      await deleteCycle(cycle.id);

      const remainingCycles = cycles.filter(
        (item) => String(item.id) !== String(cycle.id)
      );

      setCycles(remainingCycles);

      if (String(currentCycleId) === String(cycle.id)) {
        const nextCycle = remainingCycles[0] || null;
        setCurrentCycle(nextCycle);

        if (nextCycle) {
          saveCycleId(nextCycle.id);
          setCurrentCycleId(nextCycle.id);
          await refreshDashboard(nextCycle.id);
        } else {
          sessionStorage.removeItem("cycle_id");
          setCurrentCycleId(null);
          await refreshDashboard(null);
        }
      }

      showToast("Cycle deleted");
    } catch (error) {
      console.error(error);
      showToast(error.message || "Failed to delete cycle", "error");
    } finally {
      setCycleActionLoading(false);
    }
  };

  const openCycleSummary = async (cycle) => {
    if (cycle.is_history_placeholder) {
      setCycleSummary({
        label: cycle.cycle_name || formatCycleDate(cycle.start_date, {
          month: "long",
          year: "numeric"
        }),
        income: 0,
        total_spent: 0,
        total_saved: 0,
        goal_contributions: 0,
        top_spending_category: "History pending",
        goals_achieved: 0,
        summary_text:
          "This previous cycle is shown in the history list, but detailed May data is not available from the deployed API yet."
      });
      setIsSettingsModalOpen(false);
      setIsCycleSummaryModalOpen(true);
      return;
    }

    try {
      const summary = await getCycleSummary(cycle.id);
      setCycleSummary({
        ...summary,
        label: summary.cycle_name || cycle.cycle_name || formatCycleDate(
          cycle.start_date,
          {
            month: "long",
            year: "numeric"
          }
        )
      });
      setIsSettingsModalOpen(false);
      setIsCycleSummaryModalOpen(true);
    } catch (error) {
      console.error(error);
      setCycleSummary({
        label: cycle.cycle_name || formatCycleDate(cycle.start_date, {
          month: "long",
          year: "numeric"
        }),
        income: currentCycle?.income_amount || analysis?.income || 0,
        total_spent: analysis?.total_spent || 0,
        total_saved: (
          (currentCycle?.income_amount || analysis?.income || 0) -
          (analysis?.total_spent || 0) -
          goals.reduce((sum, goal) => sum + Number(goal.current_amount || 0), 0)
        ),
        goal_contributions: goals.reduce(
          (sum, goal) => sum + Number(goal.current_amount || 0),
          0
        ),
        top_spending_category: analysis?.top_category || "None",
        goals_achieved: goals.filter(
          (goal) => goal.current_amount >= goal.target_amount
        ).length,
        summary_text:
          "This summary uses the current dashboard data until cycle history is deployed."
      });
      setIsSettingsModalOpen(false);
      setIsCycleSummaryModalOpen(true);
    }
  };

  const openCycleComparison = async () => {
    if (!effectiveComparisonBaseCycleId || !effectiveComparisonTargetCycleId) {
      showToast("Choose two cycles to compare", "error");
      return;
    }

    if (
      String(effectiveComparisonBaseCycleId) ===
      String(effectiveComparisonTargetCycleId)
    ) {
      showToast("Choose two different cycles", "error");
      return;
    }

    try {
      setCycleComparisonLoading(true);
      const comparison = await getCycleComparison(
        effectiveComparisonBaseCycleId,
        effectiveComparisonTargetCycleId
      );
      setCycleComparison(comparison);
      setIsSettingsModalOpen(false);
      setIsCycleComparisonModalOpen(true);
    } catch (error) {
      console.error(error);
      showToast(error.message || "Failed to compare cycles", "error");
    } finally {
      setCycleComparisonLoading(false);
    }
  };

  const formatEGP = (value) =>
    `EGP ${Number(value || 0).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    })}`;

  const formatEGPValue = (value) =>
    Number(value || 0).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });

  const formatPercentChange = (value) =>
    value === null || value === undefined
      ? "New"
      : `${value > 0 ? "+" : ""}${Number(value).toFixed(1)}%`;

  const getCycleDisplayName = (cycle) => {
    if (!cycle) return "Cycle";

    return cycle.cycle_name || formatCycleDate(cycle.start_date, {
      month: "long",
      year: "numeric"
    });
  };

  const buildLocalChange = (current, previous) => {
    const safeCurrent = Number(current || 0);
    const safePrevious = Number(previous || 0);
    const difference = safeCurrent - safePrevious;

    return {
      current: safeCurrent,
      previous: safePrevious,
      difference,
      percentage_change:
        safePrevious === 0 ? null : (difference / safePrevious) * 100
    };
  };

  const formatSignedEGP = (value) => {
    const amount = Number(value || 0);
    const sign = amount > 0 ? "+" : amount < 0 ? "-" : "";

    return `${sign}${formatEGP(Math.abs(amount))}`;
  };

  const getChangeText = (
    row,
    metric,
    fromName = "the baseline cycle",
    toName = "the compared cycle",
    itemName = ""
  ) => {
    const difference = Number(row?.difference || 0);
    const amount = formatEGP(Math.abs(difference));
    const subject = itemName ? `${toName} ${itemName}` : toName;

    if (Math.abs(difference) < 0.01) {
      if (itemName) {
        return `${itemName} stayed almost the same in ${toName} and ${fromName}.`;
      }

      return `${metric} stayed almost the same in ${toName} and ${fromName}.`;
    }

    const direction = difference > 0 ? "higher" : "lower";
    const moreLess = difference > 0 ? "more" : "less";

    if (itemName) {
      return `${subject} spending was ${amount} ${direction} than ${fromName}.`;
    }

    if (metric === "Income") {
      return `${toName} income was ${amount} ${direction} than ${fromName}.`;
    }
    if (metric === "Total spending") {
      return `${toName} spending was ${amount} ${direction} than ${fromName}.`;
    }
    if (metric === "Remaining balance") {
      return `${toName} kept ${amount} ${moreLess} than ${fromName}.`;
    }
    if (metric === "Goal contributions") {
      return `${toName} goal contributions were ${amount} ${direction} than ${fromName}.`;
    }

    return `${toName} ${metric} changed by ${formatSignedEGP(difference)} compared with ${fromName}.`;
  };

  const getMeaningTone = (row, metric) => {
    const difference = Number(row?.difference || 0);

    if (Math.abs(difference) < 0.01) return "neutral";

    if (
      metric === "Total spending"
    ) {
      return difference > 0 ? "negative" : "positive";
    }

    return difference > 0 ? "positive" : "negative";
  };

  const calculateCycleHealthScore = (summary) => {
    const income = Math.max(Number(summary?.income || 0), 0);
    const spending = Math.max(Number(summary?.total_spending || 0), 0);
    const goalContributions = Math.max(Number(summary?.goal_contributions || 0), 0);
    const remainingBalance = Number(summary?.remaining_balance || 0);

    if (income <= 0) return 0;

    const savingsRate = Math.max(0, remainingBalance) / income;
    const goalRate = goalContributions / income;
    const expenseRate = spending / income;
    const savingsScore = Math.min(35, (savingsRate / 0.3) * 35);
    const goalScore = Math.min(20, (goalRate / 0.15) * 20);
    const expenseScore = Math.min(25, Math.max(0, (1 - expenseRate) / 0.3) * 25);
    const balanceScore = remainingBalance >= 0 ? 10 : 0;
    const incomeScore = 10;

    return Math.max(
      0,
      Math.min(
        100,
        Math.round(savingsScore + goalScore + expenseScore + balanceScore + incomeScore)
      )
    );
  };

  const makeCycleSummary = (comparison, side) => ({
    income: Number(comparison.totals.income?.[side] || 0),
    total_spending: Number(comparison.totals.total_spending?.[side] || 0),
    goal_contributions: Number(comparison.totals.goal_contributions?.[side] || 0),
    remaining_balance: Number(comparison.totals.remaining_balance?.[side] || 0)
  });

  const getHealthReasons = (comparison) => {
    const totals = comparison.totals || {};
    const reasons = [];
    const fromName = getCycleDisplayName(comparison.base_cycle);
    const toName = getCycleDisplayName(comparison.comparison_cycle);
    const totalSpending = totals.total_spending || buildLocalChange(0, 0);

    if (Math.abs(totalSpending.difference) >= 0.01) {
      reasons.push(
        totalSpending.difference > 0
          ? `${toName} spending increased compared with ${fromName}.`
          : `${toName} spending decreased compared with ${fromName}.`
      );
    }

    if (Math.abs(Number(totals.remaining_balance?.difference || 0)) >= 0.01) {
      reasons.push(
        Number(totals.remaining_balance.difference) > 0
          ? `${toName} kept more money available than ${fromName}.`
          : `${toName} kept less money available than ${fromName}.`
      );
    }

    if (Math.abs(Number(totals.goal_contributions?.difference || 0)) >= 0.01) {
      reasons.push(
        Number(totals.goal_contributions.difference) > 0
          ? `${toName} goal contributions increased compared with ${fromName}.`
          : `${toName} goal contributions decreased compared with ${fromName}.`
      );
    }

    if (Math.abs(Number(totals.income?.difference || 0)) < 0.01) {
      reasons.push(`Income stayed stable in ${toName} and ${fromName}.`);
    } else {
      reasons.push(
        Number(totals.income.difference) > 0
          ? `${toName} income increased compared with ${fromName}.`
          : `${toName} income decreased compared with ${fromName}.`
      );
    }

    return reasons.slice(0, 4);
  };

  const getCycleComparisonStory = (comparison) => {
    if (!comparison) return null;

    const totals = comparison.totals || {};
    const goalContributions =
      totals.goal_contributions || buildLocalChange(0, 0);
    const totalSpending = totals.total_spending || buildLocalChange(0, 0);
    const remainingBalance = totals.remaining_balance;
    const expenseChanges = [
      ...(comparison.categories || []).map((row) => ({
        ...row,
        scope: "Category"
      })),
      ...(comparison.subcategories || []).map((row) => ({
        ...row,
        scope: "Subcategory"
      }))
    ];
    const bestImprovement = expenseChanges
      .filter((row) => Number(row.difference || 0) < 0)
      .sort((a, b) => Number(a.difference || 0) - Number(b.difference || 0))[0];
    const biggestIncrease = expenseChanges
      .filter((row) => Number(row.difference || 0) > 0)
      .sort((a, b) => Number(b.difference || 0) - Number(a.difference || 0))[0];
    const toName = getCycleDisplayName(comparison.comparison_cycle);
    const fromName = getCycleDisplayName(comparison.base_cycle);
    const categoryIncreases = [...(comparison.categories || [])]
      .filter((row) => Number(row.difference || 0) > 0)
      .sort((a, b) => Number(b.difference || 0) - Number(a.difference || 0));
    const categoryReductions = [...(comparison.categories || [])]
      .filter((row) => Number(row.difference || 0) < 0)
      .sort((a, b) => Number(a.difference || 0) - Number(b.difference || 0));
    const subcategoryInsights = [...(comparison.subcategories || [])]
      .filter((row) => Math.abs(Number(row.difference || 0)) >= 0.01)
      .sort(
        (a, b) =>
          Math.abs(Number(b.difference || 0)) -
          Math.abs(Number(a.difference || 0))
      );
    const baseSummary = makeCycleSummary(comparison, "previous");
    const currentSummary = makeCycleSummary(comparison, "current");
    const baseHealthScore = calculateCycleHealthScore(baseSummary);
    const currentHealthScore = calculateCycleHealthScore(currentSummary);
    const remainingTone = getMeaningTone(remainingBalance, "Remaining balance");
    const spendingTone = getMeaningTone(totalSpending, "Total spending");
    const goalTone = getMeaningTone(goalContributions, "Goal contributions");

    return {
      fromName,
      toName,
      totalSpending,
      remainingBalance,
      goalContributions,
      bestImprovement,
      biggestIncrease,
      categoryIncreases,
      categoryReductions,
      subcategoryInsights,
      baseHealthScore,
      currentHealthScore,
      healthReasons: getHealthReasons(comparison),
      spendingTone,
      remainingTone,
      goalTone
    };
  };

  if (loginVerseLoading) {
    return (
      <QuranStartupPage
        arabicVerse={VERIFIED_QURAN_VERSE.arabic}
        translation={VERIFIED_QURAN_VERSE.translation}
        citation={VERIFIED_QURAN_VERSE.citation}
        durationMs={5000}
        onComplete={finishLoginVerse}
      />
    );
  }

  if (!isAuthenticated) {
    const authMode = forgotMode ? "recovery" : isRegisterMode ? "register" : "login";

    if (isOnboardingMode) {
      return (
        <BakoOnboarding
          displayName={authDisplayName}
          onDisplayNameChange={setAuthDisplayName}
          onBack={() => setIsOnboardingMode(false)}
          onComplete={() => {
            setIsOnboardingMode(false);
            setIsRegisterMode(true);
            setForgotMode(false);
            setAuthFieldErrors({});
            setAuthStatus({ message: "", tone: "error" });
          }}
        />
      );
    }

    return (
      <>
        {toastMessage && <Toast message={toastMessage} type={toastType} />}
        <BakoAuthPage
          mode={authMode}
          email={authEmail}
          password={authPassword}
          displayName={authDisplayName}
          passwordVisible={authPasswordVisible}
          loading={authLoading}
          fieldErrors={authFieldErrors}
          statusMessage={authStatus.message}
          statusTone={authStatus.tone}
          generatedToken={generatedToken}
          resetToken={resetToken}
          newPassword={newPassword}
          onEmailChange={(event) => {
            setAuthEmail(event.target.value);
            clearAuthFieldError("email");
          }}
          onPasswordChange={(event) => {
            setAuthPassword(event.target.value);
            clearAuthFieldError("password");
          }}
          onDisplayNameChange={(event) => {
            setAuthDisplayName(event.target.value);
            clearAuthFieldError("displayName");
          }}
          onTogglePassword={() => setAuthPasswordVisible((visible) => !visible)}
          onLogin={handleLogin}
          onRegister={handleRegister}
          onOpenRegister={() => {
            setIsOnboardingMode(true);
            setIsRegisterMode(false);
            setForgotMode(false);
            setAuthFieldErrors({});
            setAuthStatus({ message: "", tone: "error" });
          }}
          onOpenRecovery={() => {
            setForgotMode(true);
            setIsRegisterMode(false);
            setAuthFieldErrors({});
            setAuthStatus({ message: "", tone: "error" });
          }}
          onBackToLogin={showLoginMode}
          onRequestReset={handleForgotPassword}
          onResetTokenChange={(event) => {
            setResetToken(event.target.value);
            clearAuthFieldError("resetToken");
          }}
          onNewPasswordChange={(event) => {
            setNewPassword(event.target.value);
            clearAuthFieldError("newPassword");
          }}
          onResetPassword={handleResetPassword}
        />
      </>
    );
  }

  if (isDashboardBootstrapping) {
    return (
      <div className="auth-page login-loading-page pulse-auth-surface">
        <div className="login-verse-card login-loading-card">
          <div className="login-loading-mark" aria-hidden="true">
            <img src="/bako-icon.png" alt="" />
          </div>
          <h1 className="dashboard-title">Loading Bako...</h1>
          <p className="dashboard-subtitle">Preparing your calm money dashboard</p>
          <div className="login-spinner"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="dashboard-page pulse-error-page">
        <PulseErrorState title="Bako could not load">
          {error}
        </PulseErrorState>
      </div>
    );
  }

  return (
    <div className={`dashboard-page dashboard-vnext pulse-app ${amountsHidden ? "amounts-hidden" : ""}`}>
      <div className="dashboard-soft-shape dashboard-soft-shape-one"></div>
      <div className="dashboard-soft-shape dashboard-soft-shape-two"></div>

      <div className="dashboard-mobile-shell">
        {!currentCycleId && (
        <div className="dashboard-header dashboard-vnext-header">
          <div className="modern-brand-heading">
            <img src="/bako-icon.png" alt="Bako" />
            <div>
              <h1>
                {currentUser?.preferred_language === "ar" ? "أهلاً" : "Hi"},{" "}
                {currentUser?.display_name || currentUser?.email?.split("@")[0] || "there"}
              </h1>
              <p>{currentCycle?.cycle_name || "Bako"}</p>
            </div>
          </div>

          <div className="dashboard-header-actions">
            <button
              className="dashboard-icon-button"
              onClick={() => setIsSettingsModalOpen(true)}
              aria-label="Open settings"
            >
              <Settings size={22} />
            </button>

            <button
              className="dashboard-icon-button"
              onClick={handleLogout}
              aria-label="Logout"
            >
              <LogOut size={22} />
            </button>
          </div>
        </div>
        )}

        {toastMessage && <Toast message={toastMessage} type={toastType} />}

        {!currentCycleId ? (
          <div className={`no-cycle-card welcome-cycle-card ${
            showCycleRecovery ? "welcome-cycle-card-error" : ""
          }`}>
            <div
              className={`welcome-cycle-visual ${
                showCycleRecovery ? "" : "welcome-cycle-visual-hero"
              }`}
              aria-hidden="true"
            >
              {showCycleRecovery ? (
                <img
                  src="/bako-icon.png"
                  alt=""
                  className="welcome-error-image"
                  loading="lazy"
                  decoding="async"
                />
              ) : showNewUserPrompt ? (
                <img
                  src="/bako-icon.png"
                  alt=""
                  className="welcome-hero-image"
                  loading="lazy"
                  decoding="async"
                />
              ) : (
                <div className="welcome-loading-orb" />
              )}
            </div>

            <div className="welcome-cycle-copy">
              <span>
                {showCycleRecovery
                  ? "Cycles unavailable"
                  : showCyclePickerPrompt
                    ? "Cycle not selected"
                    : showCycleLoadingPrompt
                      ? "Loading cycles"
                      : "Welcome to Bako"}
              </span>
              <strong>
                {showCycleRecovery
                  ? "We couldn't load your saved cycles"
                  : showCyclePickerPrompt
                  ? "Choose a financial cycle to continue"
                  : showCycleLoadingPrompt
                    ? "Checking your financial cycles"
                    : "Let's create your first cycle"}
              </strong>
              <p>
                {showCycleRecovery
                  ? "This usually means the backend cycle endpoint needs the latest deployment or a restart. Your account is not new."
                  : showCyclePickerPrompt
                    ? "You already have saved cycles. Choose the one you want to view and Bako will update the dashboard."
                    : showCycleLoadingPrompt
                      ? "One moment while Bako finds the right cycle for your account."
                      : "Add your income dates once, then Bako will calculate your daily allowance and help you stay on track."}
              </p>
            </div>

            <div className="welcome-cycle-steps">
              {showCycleRecovery ? (
                <>
                  <span>Existing account detected</span>
                  <span>Cycle data could not be loaded</span>
                  <span>Retry after backend deploy/restart</span>
                </>
              ) : showCyclePickerPrompt ? (
                <>
                  <span>{cycles.length} saved cycle{cycles.length === 1 ? "" : "s"} found</span>
                  <span>Select the active cycle from settings</span>
                  <span>Your dashboard will update automatically</span>
                </>
              ) : showCycleLoadingPrompt ? (
                <>
                  <span>Checking current cycle</span>
                  <span>Loading saved cycles</span>
                  <span>Preparing dashboard</span>
                </>
              ) : showNewUserPrompt ? (
                <>
                  <span>Create your income cycle</span>
                  <span>Record your spending</span>
                  <span>Track spending daily</span>
                </>
              ) : (
                <>
                  <span>Checking account state</span>
                  <span>Restoring dashboard</span>
                  <span>Preparing Bako</span>
                </>
              )}
            </div>

            <button
              className="primary-button welcome-cycle-button"
              disabled={showCycleLoadingPrompt}
              onClick={() =>
                showCycleRecovery
                  ? window.location.reload()
                  : showCyclePickerPrompt
                  ? setIsSettingsModalOpen(true)
                  : setIsCycleModalOpen(true)
              }
            >
              {showCycleRecovery
                ? "Retry Loading Cycles"
                : showCyclePickerPrompt
                  ? "Open Financial Cycles"
                  : showCycleLoadingPrompt
                    ? "Still Loading..."
                    : "Create Financial Cycle"}
            </button>
          </div>
        ) : (
        <>
          <ModernDashboard
            language={currentUser?.preferred_language || "en"}
            userName={userDisplayName}
            currentCycle={currentCycle}
            budgetData={budgetData}
            analysis={analysis}
            goals={goals}
            paymentSummary={paymentSummary}
            creditCardExpenses={creditCardExpenses}
            dailyTable={dailyTable}
            recentExpenses={dashboardRecentExpenses}
            onOpenAsk={() => {
              setAIView("chat");
              setSelectedAIHistoryId(null);
              setIsAIModalOpen(true);
            }}
            onOpenSettings={() => setIsSettingsModalOpen(true)}
            onLogout={handleLogout}
            onOpenSpending={() => setDashboardPanel("spending")}
            onOpenBudget={() => setDashboardPanel("budget")}
            onOpenGoals={() => setDashboardPanel("goals")}
            onOpenCard={() => setDashboardPanel("card")}
            onOpenDay={(day) => openDayDetails(day)}
            onExpandedCardChange={handleEditorialCardChange}
            onRecordSpending={openTodayDetails}
            amountsHidden={amountsHidden}
            onAmountsHiddenChange={setAmountsHidden}
          />
        </>
        )}

      </div>

      <PulseConfirmDialog request={confirmationRequest} onResolve={resolveConfirmation} />

      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={selectedDay ? "Daily details" : "Finance Insights"}
        subtitle={selectedDay ? "Spending, goals and money left" : ""}
        direction={isArabicUI ? "rtl" : "ltr"}
        variant={selectedDay ? "modern-page" : ""}
      >
        {selectedDay ? (
          <div className="day-details-carousel ai-carousel">
            <div
              className="day-details-carousel-viewport ai-carousel-viewport"
              onPointerDown={handleDayDetailsPointerDown}
              onPointerMove={handleDayDetailsPointerMove}
              onPointerUp={finishDayDetailsDrag}
              onPointerCancel={finishDayDetailsDrag}
            >
              <div
                className={`day-details-carousel-track ai-carousel-track ${
                  isDayDetailsDragging ? "is-dragging" : ""
                }`}
                style={{
                  transform: `translate3d(calc(-100% + ${dayDetailsDragOffset}px), 0, 0)`
                }}
              >
                {dayDetailSlides.map((day, index) => (
                  <div
                    className="day-details-carousel-slide ai-carousel-slide"
                    key={day?.date || `empty-${index}`}
                    aria-hidden={index !== 1}
                  >
                    {day ? (
                      index === 1 ? (
          <div
            key={selectedDay.date}
            className={`day-details-card day-slide-${dayDetailsDirection}`}
          >
            <div className="day-details-navigation">
              <button
                type="button"
                onClick={() => navigateDayDetails(-1)}
                disabled={!canNavigatePrevious}
                aria-label="Previous day"
              >
                <ChevronLeft size={20} />
              </button>

              <div>
                <span>Selected day</span>
                <strong>{formatCycleDate(selectedDay.date, {
                  month: "long",
                  day: "numeric",
                  year: "numeric"
                })}</strong>
              </div>

              <button
                type="button"
                onClick={() => navigateDayDetails(1)}
                disabled={!canNavigateNext}
                aria-label="Next day"
              >
                <ChevronRight size={20} />
              </button>
            </div>

            <div className="modal-stats">
              <p>
                <span>Allowance</span>
                <strong>{formatEGP(selectedDay.available_today)}</strong>
              </p>
              <p>
                <span>Expenses</span>
                <strong>{formatEGP(selectedDayDailyExpenses)}</strong>
              </p>
              <p>
                <span>Goal savings</span>
                <strong>{formatEGP(selectedDayGoalContributions)}</strong>
              </p>
              <p>
                <span>Used today</span>
                <strong>{formatEGP(selectedDayUsedToday)}</strong>
              </p>
              <p>
                <span>Left today</span>
                <strong>{formatEGP(selectedDay.remaining_today)}</strong>
                <em className={`day-allowance-status ${
                  Number(selectedDay.remaining_today || 0) >= 0
                    ? "is-within"
                    : "is-over"
                }`}>
                  {Number(selectedDay.remaining_today || 0) >= 0
                    ? "Within allowance"
                    : "Over allowance"}
                </em>
              </p>
            </div>

            <div className="modal-ai-box">
              <div className="expense-list-section">
  <div className="expense-list-heading">
    <h3>Expenses</h3>
    <button
      className="day-add-expense-button"
      onClick={() => {
        setShowDayExpenseForm((current) => !current);
      }}
    >
      <Plus size={16} />
      Add Expense
    </button>
  </div>
  {showDayExpenseForm && (
    <div className="day-expense-form">
      <ExpenseForm
        amount={amount}
        setAmount={setAmount}
        description={expenseDescription}
        setDescription={setExpenseDescription}
        selectedCategory={selectedCategory}
        setSelectedCategory={handleCategoryChange}
        selectedSubcategory={selectedSubcategory}
        setSelectedSubcategory={setSelectedSubcategory}
        paymentChannel={paymentChannel}
        setPaymentChannel={setPaymentChannel}
        creditCards={creditCards}
        selectedCreditCard={selectedCreditCard}
        setSelectedCreditCard={setSelectedCreditCard}
        newCreditCardName={newCreditCardName}
        setNewCreditCardName={setNewCreditCardName}
        onCreateCreditCard={handleCreateCreditCard}
        expenseDate={selectedDay.date}
        setExpenseDate={() => {}}
        categories={categories}
        subcategories={subcategories}
        handleSubmit={handleSubmit}
        expenseLoading={expenseLoading}
        onCreateCategory={handleCreateCategory}
        onCreateSubcategory={handleCreateSubcategory}
        onRenameCategory={handleRenameCategory}
        onArchiveCategory={handleArchiveCategory}
        onRenameSubcategory={handleRenameSubcategory}
        onArchiveSubcategory={handleArchiveSubcategory}
        onSuggestCategory={handleSuggestExpenseCategory}
        onUseSuggestedCategoryPair={handleUseSuggestedCategoryPair}
        onCreateSuggestedCategoryPair={handleCreateSuggestedCategoryPair}
        onConfirm={requestConfirmation}
        lockedDate
      />
    </div>
  )}
  {editingExpense && (
  <div className="edit-expense-box">
    <label className="edit-expense-field">
      <span>Amount</span>
    <input
      type="number"
      value={editAmount}
      onChange={(e) =>
        setEditAmount(e.target.value)
      }
      className="expense-input"
    />
    </label>

    <label className="edit-expense-field">
      <span>Where did the money go?</span>
      <select
        className="expense-input"
        value={editCategory}
        onChange={(event) => handleEditExpenseCategoryChange(event.target.value)}
      >
        <option value="">Choose where it went</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </select>
    </label>

    <label className="edit-expense-field">
      <span>What kind?</span>
      <select
        className="expense-input"
        value={editSubcategory}
        onChange={(event) => (
          handleEditExpenseSubcategoryChange(event.target.value)
        )}
        disabled={!editCategory}
      >
        <option value="">Choose what kind</option>
        {editSubcategories.map((subcategory) => (
          <option key={subcategory.id} value={subcategory.id}>
            {formatSubcategoryName(subcategory.name)}
          </option>
        ))}
      </select>
    </label>

    <div className="edit-expense-global-names">
      <p>Rename for all expenses</p>
      <small>Changing these names updates them everywhere.</small>
      <input
        className="expense-input"
        value={editCategoryName}
        onChange={(event) => setEditCategoryName(event.target.value)}
        placeholder="Category name, for example Home"
        aria-label="Rename category for all expenses"
        maxLength={100}
      />
      <input
        className="expense-input"
        value={editSubcategoryName}
        onChange={(event) => setEditSubcategoryName(event.target.value)}
        placeholder="Type name, for example Maintenance"
        aria-label="Rename expense type for all expenses"
        maxLength={100}
      />
    </div>

    <label className="edit-expense-field">
      <span>Paid with</span>
    <select
      className="expense-input"
      value={editPaymentChannel}
      onChange={(event) => setEditPaymentChannel(event.target.value)}
      aria-label="Payment channel"
    >
      <option value="cash">Cash</option>
      <option value="credit_card">Credit Card</option>
    </select>
    </label>

    {editPaymentChannel === "credit_card" && (
      <div className="edit-credit-card-section">
        <span className="edit-credit-card-label">Credit card</span>
        <div className="expense-card-choice">
          <select
            className="expense-input"
            value={editCreditCard}
            onChange={(event) => setEditCreditCard(event.target.value)}
            aria-label="Credit card"
          >
            <option value="">Unassigned card</option>
            {creditCards.map((card) => (
              <option key={card.id} value={card.id}>{card.name}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setShowEditCreditCardCreate((current) => !current)}
            aria-expanded={showEditCreditCardCreate}
          >
            + Add card
          </button>
        </div>
        {showEditCreditCardCreate && (
          <div className="expense-choice-create expense-card-create">
            <input
              className="expense-input"
              value={newCreditCardName}
              onChange={(event) => setNewCreditCardName(event.target.value)}
              placeholder="Card name"
              maxLength={100}
            />
            <button
              type="button"
              onClick={async () => {
                const created = await handleCreateCreditCard();
                if (created) {
                  setEditCreditCard(String(created.id));
                  setShowEditCreditCardCreate(false);
                }
              }}
              disabled={!newCreditCardName.trim()}
            >
              Add
            </button>
          </div>
        )}
      </div>
    )}

    <div className="edit-actions">
      <button
        className="expense-edit-btn"
        onClick={handleUpdateDailyExpense}
      >
        Save changes
      </button>

      <button
        className="expense-delete-btn"
        onClick={() =>
          setEditingExpense(null)
        }
      >
        Cancel
      </button>
    </div>
  </div>
)}

  {detailsLoading ? (
    <p className="ai-text">Loading expenses...</p>
  ) : dailyDetails.length === 0 && dailyGoalContributions.length === 0 ? (
    <p className="ai-text">No money used on this day.</p>
  ) : (
    <>
    {dailyDetails.length > 0 && (
      <div className="expense-list">
{dailyDetails.map((expense) => (
  <div
    key={expense.id}
    className="expense-list-item"
  >
    <div className="expense-info">
      <div className="expense-info-row">
        <strong>
          {expense.category_name}
        </strong>

        <em>
          {expense.amount} EGP
        </em>
      </div>

      <span>
        {formatSubcategoryName(expense.subcategory_name)}
      </span>
      <small className="expense-payment-channel">
        {expense.payment_channel === "credit_card"
          ? `Credit Card${expense.credit_card_name ? ` · ${expense.credit_card_name}` : ""}`
          : "Cash"}
      </small>

      {expense.description && (
        <small>
          {expense.description}
        </small>
      )}
    </div>

    <div className="expense-actions">
      <div className="expense-buttons">
        <button
          className="expense-edit-btn"
          onClick={() => handleStartEditExpense(expense)}
           >
            Edit
        </button>
        <button
          className="expense-delete-btn"
          onClick={async () => {
            if (!(await requestConfirmation({
              title: "DELETE THIS EXPENSE?",
              message: "THIS EXPENSE WILL BE PERMANENTLY REMOVED FROM THE SELECTED DAY AND FINANCIAL CYCLE.",
              confirmLabel: "DELETE EXPENSE"
            }))) {
              return;
            }

            try {
           await deleteExpense(expense.id);

setDailyDetails((currentExpenses) =>
  currentExpenses.filter((item) => item.id !== expense.id)
);

const updatedBudget = await getBudgetData(currentCycleId);
const updatedTable = updatedBudget.daily_table || [];
setDailyTable(updatedTable);
setBudgetData(updatedBudget);

const updatedDay = updatedTable.find(
  (day) => day.date === selectedDay.date
);

if (updatedDay) {
  setSelectedDay(updatedDay);
}

const updatedAnalysis = await getAnalysis(currentCycleId);
setAnalysis(updatedAnalysis);
const updatedPaymentSummary = await getPaymentSummary(currentCycleId);
setPaymentSummary(updatedPaymentSummary);

showToast("Expense deleted");
            } catch (error) {
              console.error(error);

              showToast(
                "Delete failed",
                "error"
              );
            }
          }}
        >
          Delete
        </button>
      </div>
    </div>
  </div>
))}
      </div>
    )}

    {dailyGoalContributions.length > 0 && (
      <div className="goal-contribution-list">
        <h4>Goal contributions</h4>
        {dailyGoalContributions.map((contribution) => (
          <div
            key={contribution.id}
            className="expense-list-item goal-contribution-item"
          >
            <div className="expense-info">
              <div className="expense-info-row">
                <strong>{contribution.goal_name}</strong>
                <em>{formatEGP(contribution.amount)}</em>
              </div>
              <span>Moved into goal progress</span>
            </div>
          </div>
        ))}
      </div>
    )}
    </>
  )}
</div>
          </div>
          </div>
                      ) : (
                        <div className="day-details-card day-details-preview-card">
                          <div className="day-details-navigation">
                            <span />
                            <div>
                              <span>Details</span>
                              <strong>{day.date}</strong>
                            </div>
                            <span />
                          </div>

                          <div className="modal-stats">
                            <p>
                              <span>Allowance</span>
                              <strong>{formatEGP(day.available_today)}</strong>
                            </p>
                            <p>
                              <span>Expenses</span>
                              <strong>{formatEGP(
                                day.daily_expenses_today ?? day.spent_today
                              )}</strong>
                            </p>
                            <p>
                              <span>Goal savings</span>
                              <strong>{formatEGP(day.goal_contributions_today)}</strong>
                            </p>
                            <p>
                              <span>Used today</span>
                              <strong>{formatEGP(day.used_today ?? day.spent_today)}</strong>
                            </p>
                            <p>
                              <span>Left today</span>
                              <strong>{formatEGP(day.remaining_today)}</strong>
                            </p>
                          </div>
                        </div>
                      )
                    ) : (
                      <div className="day-details-card day-details-preview-card day-details-empty-preview" />
                    )}
                </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <p className="ai-text">AI financial insights will appear here later.</p>
        )}
      </Modal>


      <Modal
        isOpen={Boolean(dashboardPanel)}
        onClose={() => setDashboardPanel(null)}
        title={(pageText[dashboardPanel] || pageText.pace)[0]}
        subtitle={(pageText[dashboardPanel] || pageText.pace)[1]}
        direction={isArabicUI ? "rtl" : "ltr"}
        variant="modern-page"
      >
        {dashboardPanel === "budget" && (
          <div className="modern-budget-panel">
            <section className="modern-panel-total">
              <span>{currentCycle?.cycle_name || "Current cycle"}</span>
              <strong>{formatEGP(currentCycle?.income_amount || 0)}</strong>
              <small>Total cycle income</small>
            </section>
            <section className="modern-budget-consumed">
              <div>
                <span>Consumed so far</span>
                <strong>{Math.max(0, Math.round(
                  ((Number(currentCycle?.income_amount || 0) -
                    Number(budgetData?.remaining_total_budget || 0)) /
                    Math.max(Number(currentCycle?.income_amount || 0), 1)) * 100
                ))}%</strong>
              </div>
              <span className="modern-progress"><i style={{ width: `${Math.min(100, Math.max(0,
                ((Number(currentCycle?.income_amount || 0) - Number(budgetData?.remaining_total_budget || 0)) /
                Math.max(Number(currentCycle?.income_amount || 0), 1)) * 100
              ))}%` }} /></span>
              <small>{formatEGP(budgetData?.remaining_total_budget || 0)} left</small>
            </section>
            <section className="modern-budget-add">
              <label htmlFor="budget-addition">Add more budget to this cycle</label>
              <div>
                <input
                  id="budget-addition"
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={budgetAddition}
                  onChange={(event) => setBudgetAddition(event.target.value)}
                  placeholder="Amount in EGP"
                />
                <button className="pulse-button pulse-button-primary" onClick={handleAddBudget} disabled={budgetAdditionLoading || !Number(budgetAddition)}>
                  {budgetAdditionLoading ? "Adding..." : "Add budget"}
                </button>
              </div>
              <small>Every addition is recorded in the cycle history.</small>
            </section>
          </div>
        )}

        {dashboardPanel === "spending" && (
          <SpendingAnalysis
            analysis={analysis}
            cycleName={currentCycle?.cycle_name}
            amountsHidden={amountsHidden}
          />
        )}

        {dashboardPanel === "goals" && (
          <div className="modern-panel-list modern-goals-panel">
            <span className="modern-goals-panel-kicker">
              {currentUser?.preferred_language === "ar" ? "الأهداف النشطة" : "Active goals"}
            </span>
            {goals.length === 0 ? (
              <p>No goals yet. Create one when you are ready.</p>
            ) : goals.map((goal) => {
              const progress = Math.min(100, Math.round(
                (Number(goal.current_amount || 0) /
                  Math.max(Number(goal.target_amount || 0), 1)) * 100
              ));
              return (
                <button className="modern-goal-row" key={goal.id} onClick={() => openGoalModal(goal)}>
                  <span className="modern-goal-row-heading">
                    <span>
                      <strong>{goal.name}</strong>
                      <small>{formatEGP(goal.current_amount)} saved</small>
                    </span>
                    <em>{progress}%</em>
                  </span>
                  <span className="modern-goal-row-progress" aria-hidden="true">
                    <i style={{ width: `${progress}%` }} />
                  </span>
                </button>
              );
            })}
            <button className="modern-panel-primary pulse-button pulse-button-accent" onClick={() => openGoalModal()}>
              <span><Plus size={18} /> Create goal</span>
              {currentUser?.preferred_language === "ar" ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
            </button>
          </div>
        )}

        {dashboardPanel === "card" && (
          <div className="modern-panel-list modern-card-panel">
            <div className="modern-panel-total">
              <span>Outstanding</span>
              <span className="modern-card-money modern-card-money-total">
                <small>EGP</small>
                <strong>{formatEGPValue(paymentSummary?.outstanding_credit_card || 0)}</strong>
              </span>
            </div>
            <div className="modern-card-add">
              <input
                value={newCreditCardName}
                onChange={(event) => setNewCreditCardName(event.target.value)}
                placeholder="Card name, for example CIB Visa"
                maxLength={80}
              />
              <button className="pulse-button pulse-button-accent" onClick={handleCreateCreditCard} disabled={!newCreditCardName.trim()}><Plus size={17} /> Add card</button>
            </div>
            {creditCardExpenses.length === 0 && creditCards.length === 0 ? (
              <p>No credit card spending in this cycle.</p>
            ) : (() => {
              const configuredCardIds = new Set(
                creditCards.map((card) => String(card.id))
              );
              const cardGroups = creditCards.map((card) => ({
                id: String(card.id),
                name: card.name,
                expenses: creditCardExpenses.filter(
                  (expense) => String(expense.credit_card_id) === String(card.id)
                )
              }));
              const unassignedExpenses = creditCardExpenses.filter(
                (expense) => !expense.credit_card_id ||
                  !configuredCardIds.has(String(expense.credit_card_id))
              );

              if (unassignedExpenses.length > 0) {
                cardGroups.push({
                  id: "unassigned",
                  name: "Unassigned card",
                  expenses: unassignedExpenses
                });
              }

              return cardGroups.map((group) => {
                const groupOutstanding = group.expenses
                  .filter((expense) => !expense.settled_at)
                  .reduce((sum, expense) => sum + Number(expense.amount || 0), 0);
                const groupOutstandingCount = group.expenses.filter(
                  (expense) => !expense.settled_at
                ).length;

                return (
                  <section className="modern-credit-card-group" key={group.id}>
                    <div className="modern-credit-card-heading">
                      <span>
                        <strong>{group.name}</strong>
                        <small>
                          {groupOutstandingCount} outstanding {groupOutstandingCount === 1 ? "transaction" : "transactions"}
                        </small>
                      </span>
                      <span className="modern-card-money modern-card-money-group">
                        <small>EGP</small>
                        <strong>{formatEGPValue(groupOutstanding)}</strong>
                      </span>
                    </div>

                    {group.expenses.length === 0 ? (
                      <p className="modern-credit-card-empty">
                        No purchases on this card in the current cycle.
                      </p>
                    ) : (
                      <div className="modern-credit-card-transactions">
                        {group.expenses.map((expense) => (
                          <button
                            className="modern-credit-card-transaction"
                            key={expense.id}
                            onClick={() => handleCardSettlement(expense)}
                          >
                            <span>
                              <strong>{expense.subcategory || expense.category}</strong>
                              <small>{expense.expense_date}</small>
                            </span>
                            <span className="modern-credit-card-transaction-value">
                              <span className="modern-card-money modern-card-money-transaction">
                                <small>EGP</small>
                                <strong>{formatEGPValue(expense.amount)}</strong>
                              </span>
                              <small className={expense.settled_at ? "is-settled" : "is-outstanding"}>
                                {expense.settled_at ? "Settled" : "Outstanding"}
                              </small>
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </section>
                );
              });
            })()}
            <small>Settlement is informational. It never deducts the budget again.</small>
          </div>
        )}

        {dashboardPanel === "pace" && (
          <div className="modern-pace-panel">
            <section className="modern-pace-hero">
              <div className="pace-safe-copy">
                <span>{!paceSelectedDay || paceSelectedDay.date === todayKey
                  ? pageText.safeToday
                  : `Safe on ${formatCycleDate(paceSelectedDay?.date, {
                      month: "short",
                      day: "numeric"
                    })}`}</span>
                <small>EGP</small>
                <strong>{formatEGPValue(
                  paceSelectedDay?.available_today ||
                  budgetData?.current_daily_allowance ||
                  0
                )}</strong>
              </div>
              <em>{Number(paceSelectedDay?.used_today || 0) <=
                Number(paceSelectedDay?.available_today || 0)
                  ? pageText.onTrack
                  : "Over"}</em>
              <div
                className="pace-bars"
                aria-label="Recent daily spending. Swipe right for the previous week."
                onPointerDown={handlePaceWeekPointerDown}
                onPointerUp={handlePaceWeekPointerUp}
                onPointerCancel={handlePaceWeekPointerUp}
              >
                {paceChartDays.map((day) => {
                  const spent = Number(day.used_today || 0);
                  const allowance = Number(day.available_today || 0);
                  const isOverAllowance = spent > allowance;
                  const barHeight = spent <= 0
                    ? 0
                    : Math.min(100, 18 + ((spent / maxPaceChartValue) * 82));
                  return (
                  <button
                    className={`pace-bar-item ${isOverAllowance ? "is-over-allowance" : ""}`}
                    key={day.date}
                    aria-label={`${formatCycleDate(day.date, { month: "short", day: "numeric" })}: ${formatEGP(spent)} spent${isOverAllowance ? ", over allowance" : ""}`}
                    onClick={() => {
                      if (paceWeekSwipeRef.current.didSwipe) {
                        paceWeekSwipeRef.current.didSwipe = false;
                        return;
                      }
                      setDashboardPanel(null);
                      openDayDetails(day);
                    }}
                  >
                    <span className="pace-bar-track">
                      <i style={{ height: `${barHeight}%` }} />
                    </span>
                    <b>{formatCycleDate(day.date, { day: "numeric" })}</b>
                  </button>
                  );
                })}
              </div>
            </section>

            <section className="modern-pace-calendar pulse-content-card">
              <PulseCalendar
                days={cycleDays}
                selectedDate={paceSelectedDay?.date}
                language={uiLanguage}
                tone="dark"
                amountsHidden={amountsHidden}
                onSelect={(day) => setPaceSelectedDate(day.date)}
              />
              {paceSelectedDay && (
                <div className="modern-calendar-summary">
                  <span><small>{formatCycleDate(paceSelectedDay.date, { month: "short", day: "numeric" })}</small><strong>{pageText.selectedDay}</strong></span>
                  <span><small>{pageText.allowed}</small><strong>{formatEGP(paceSelectedDay.available_today || 0)}</strong></span>
                  <span><small>{pageText.usedLeft}</small><strong>{formatEGP(paceSelectedDay.used_today || 0)} / {formatEGP(paceSelectedDay.remaining_today || 0)}</strong></span>
                </div>
              )}
            </section>
          </div>
        )}
      </Modal>

      <Modal
  isOpen={isAIModalOpen}
  onClose={() => setIsAIModalOpen(false)}
  title={pageText.ask[0]}
  subtitle={pageText.ask[1]}
  direction={isArabicUI ? "rtl" : "ltr"}
  variant="modern-page"
>
 <div className="ai-modal-container pulse-content-card">
    <div
      className="ai-chat-panel"
      id="ai-coach-chat-panel"
    >
      {aiView === "chat" && <div className="ai-chat-toolbar">
        <button
          type="button"
          className="is-active"
          onClick={() => {
            setAIView("history");
            setSelectedAIHistoryId(null);
          }}
        >
          History
        </button>
      </div>}
      {aiView === "history" ? (
        <AIConversationHistory
          exchanges={aiHistoryExchanges}
          selectedId={selectedAIHistoryId}
          onSelect={setSelectedAIHistoryId}
          onBack={() => {
            setAIView("chat");
            setSelectedAIHistoryId(null);
          }}
          language={uiLanguage}
        />
      ) : (
        <>
      <div className="ai-chat-suggestions" aria-label="Suggested questions">
        {[
          "How is my budget pace?",
          "What is my highest spending category?",
          "How can I stay on track with my goals?"
        ].map((question) => (
          <button
            type="button"
            key={question}
            onClick={(event) => handleAskAICoach(event, question)}
            disabled={aiChatLoading}
          >
            {question}
          </button>
        ))}
      </div>

      <div className="ai-chat-messages" aria-live="polite">
        {aiChatMessages.map((message, index) => (
          <article
            className={`ai-chat-message ai-chat-message-${message.role} ${
              message.isError ? "is-error" : ""
            }`}
            key={message.id || `${message.role}-${index}`}
          >
            {message.headline && <strong>{message.headline}</strong>}
            <p>{message.text}</p>
            {message.action && <em>{message.action}</em>}
            {message.actions?.length > 0 && (
              <div className="ai-chat-actions">
                {message.actions.map((action) => (
                  <button
                    type="button"
                    key={action.action_id}
                    onClick={() => handleAIChatGoalAction(action, index)}
                    disabled={Boolean(aiActionLoading) || action.applied}
                  >
                    {action.applied
                      ? "Contribution added"
                      : aiActionLoading === action.action_id
                        ? "Adding..."
                        : action.label}
                  </button>
                ))}
                <small>
                  Amount checked by Bako. A contribution is recorded only when
                  you press the button.
                </small>
              </div>
            )}
          </article>
        ))}
        {aiChatLoading && (
          <article className="ai-chat-message ai-chat-message-assistant is-loading">
            <span />
            <span />
            <span />
          </article>
        )}
      </div>

      <form className="ai-chat-form" onSubmit={handleAskAICoach}>
        <label htmlFor="ai-coach-question">Ask about this cycle</label>
        <div>
          <input
            id="ai-coach-question"
            value={aiQuestion}
            onChange={(event) => setAIQuestion(event.target.value)}
            placeholder="Example: How much did I spend on supermarket?"
            maxLength={500}
            disabled={aiChatLoading}
          />
          <button
            className="pulse-black-action pulse-black-action-compact"
            type="submit"
            disabled={aiChatLoading || !aiQuestion.trim()}
          >
            <span>{aiChatLoading ? "Thinking..." : "Ask"}</span>
            {isArabicUI ? <ChevronLeft className="pulse-black-action-arrow" size={15} /> : <ChevronRight className="pulse-black-action-arrow" size={15} />}
          </button>
        </div>
        <small>
          Answers are read-only. Goal contributions require your button press.
        </small>
      </form>
        </>
      )}
    </div>
</div>
</Modal>

      <Modal
        isOpen={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
        title={pageText.settings[0]}
        subtitle={pageText.settings[1]}
        direction={isArabicUI ? "rtl" : "ltr"}
        variant="modern-page"
      >
        <div className="settings-modal-content">
          <div className="modern-settings-card">
            <div className="modern-settings-row">
              <span><strong>{pageText.profileName}</strong></span>
              <b>{userDisplayName}</b>
            </div>
            <div className="modern-settings-row">
              <span><strong>{pageText.currentCycle}</strong><small>{cycleMonthLabel}</small></span>
              <b>{currentCycle?.cycle_name || "-"}</b>
            </div>
            <div className="modern-settings-row">
              <span><strong>{pageText.currency}</strong><small>{isArabicUI ? "عملة العرض" : "Display currency"}</small></span>
              <b>EGP</b>
            </div>
            <div className="modern-settings-row modern-language-row">
              <span><strong>{pageText.language}</strong><small>{pageText.languageHint}</small></span>
              <div className="modern-language-switch" aria-label="Application language">
                <button
                  className={uiLanguage === "en" ? "is-active" : ""}
                  onClick={() => handleLanguageChange("en")}
                  aria-pressed={uiLanguage === "en"}
                >
                  English
                </button>
                <button
                  className={uiLanguage === "ar" ? "is-active" : ""}
                  onClick={() => handleLanguageChange("ar")}
                  aria-pressed={uiLanguage === "ar"}
                >
                  العربية
                </button>
              </div>
            </div>
          </div>

          <section className="settings-financial-cycles">
            <div className="settings-section-heading">
              <h3>{pageText.financialCycles}</h3>
              <button onClick={() => {
                setIsSettingsModalOpen(false);
                setIsCycleModalOpen(true);
              }}>
                {pageText.createCycle}
              </button>
            </div>

            <div className="cycle-history-list">
            {cycleHistory.length === 0 ? (
              <p className="drawer-empty-text">{pageText.noCycles}</p>
            ) : (
              cycleHistory.slice(0, 6).map((cycle) => {
                const isCurrent = String(cycle.id) === String(currentCycleId);
                return (
                  <div
                    key={cycle.id}
                    className={`cycle-history-item ${
                      isCurrent ? "is-selected" : ""
                    }`}
                  >
                    <div>
                      <strong>{cycle.cycle_name || "Monthly Income"}</strong>
                      <span>
                        {formatCycleDate(cycle.start_date, {
                          month: "short",
                          day: "numeric"
                        })}{" "}
                        -{" "}
                        {formatCycleDate(cycle.end_date, {
                          month: "short",
                          day: "numeric",
                          year: "numeric"
                        })}
                      </span>
                    </div>
                    <em className={`cycle-status cycle-status-${cycle.status || "ended"}`}>
                      {isCurrent
                        ? pageText.selected
                        : cycle.is_history_placeholder
                          ? pageText.previous
                          : cycle.status || "ended"}
                    </em>
                    <div className="cycle-history-actions">
                      {!cycle.is_history_placeholder && !isCurrent && (
                        <button onClick={() => switchCycle(cycle)}>
                          {pageText.use}
                        </button>
                      )}
                      <button
                        className="cycle-summary-button pulse-black-action pulse-black-action-compact"
                        onClick={() => openCycleSummary(cycle)}
                      >
                        <span>{pageText.summary}</span>
                        {isArabicUI ? <ChevronLeft className="pulse-black-action-arrow" size={15} /> : <ChevronRight className="pulse-black-action-arrow" size={15} />}
                      </button>
                      {!cycle.is_history_placeholder && (
                        <>
                          <button onClick={() => openEditCycleModal(cycle)}>
                            {pageText.editName}
                          </button>
                          <button
                            className="is-delete"
                            onClick={() => handleDeleteCycle(cycle)}
                            disabled={cycleActionLoading}
                          >
                            {pageText.delete}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })
            )}
            </div>

            {comparableCycles.length >= 2 && (
              <div className="cycle-compare-panel">
              <div className="cycle-compare-heading">
                <strong>{pageText.compareCycles}</strong>
                <span>{pageText.compareHint}</span>
              </div>
              <div className="cycle-compare-controls">
                <label>
                  <span>{pageText.from}</span>
                  <select
                    value={effectiveComparisonBaseCycleId}
                    onChange={(event) =>
                      setComparisonBaseCycleId(event.target.value)
                    }
                  >
                    {comparableCycles.map((cycle) => (
                      <option key={cycle.id} value={cycle.id}>
                        {cycle.cycle_name || "Monthly Income"}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>{pageText.to}</span>
                  <select
                    value={effectiveComparisonTargetCycleId}
                    onChange={(event) =>
                      setComparisonTargetCycleId(event.target.value)
                    }
                  >
                    {comparableCycles.map((cycle) => (
                      <option key={cycle.id} value={cycle.id}>
                        {cycle.cycle_name || "Monthly Income"}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <button
                className="primary-button cycle-compare-button"
                onClick={openCycleComparison}
                disabled={cycleComparisonLoading}
              >
                {cycleComparisonLoading ? pageText.comparing : pageText.compareCycles}
              </button>
              </div>
            )}
          </section>
        </div>
      </Modal>

      <Modal
        isOpen={isCycleSummaryModalOpen}
        onClose={() => setIsCycleSummaryModalOpen(false)}
        title={cycleSummary?.label || "Cycle Summary"}
      >
        {cycleSummary && (
          <div className="cycle-summary-content">
            <div className="cycle-summary-grid">
              <div>
                <span>Income</span>
                <strong>{formatEGP(cycleSummary.income)}</strong>
              </div>
              <div>
                <span>Total Spent</span>
                <strong>{formatEGP(cycleSummary.total_spent)}</strong>
              </div>
              <div>
                <span>Total Saved</span>
                <strong>{formatEGP(cycleSummary.total_saved)}</strong>
              </div>
              <div>
                <span>Goal Contributions</span>
                <strong>{formatEGP(cycleSummary.goal_contributions)}</strong>
              </div>
              <div>
                <span>Top Category</span>
                <strong>{cycleSummary.top_spending_category || "None"}</strong>
              </div>
              <div>
                <span>Goals Achieved</span>
                <strong>{cycleSummary.goals_achieved}</strong>
              </div>
            </div>
            <div className="cycle-summary-ai">
              <span className="cycle-summary-ai-label">Bako summary</span>
              <p>{cycleSummary.summary_text}</p>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={isCycleComparisonModalOpen}
        onClose={() => setIsCycleComparisonModalOpen(false)}
        title="Cycle Comparison"
      >
        {cycleComparison && (() => {
          const story = getCycleComparisonStory(cycleComparison);
          const metricRows = [
            ["Income", cycleComparison.totals.income],
            ["Total spending", story.totalSpending],
            ["Remaining balance", cycleComparison.totals.remaining_balance],
            ["Goal contributions", story.goalContributions]
          ];
          const chartMax = Math.max(
            ...metricRows.flatMap(([, row]) => [
              Number(row.previous || 0),
              Number(row.current || 0)
            ]),
            1
          );

          return (
            <div className="cycle-comparison-content">
              <div className="cycle-comparison-title cycle-ai-summary">
                <span>Financial review</span>
                <strong>{story.toName} vs {story.fromName}</strong>
                <p>
                  A quick read on where money moved between these two cycles.
                </p>
              </div>

              <div className="cycle-comparison-summary-grid">
                <div
                  className={`cycle-comparison-summary-card tone-${story.spendingTone}`}
                >
                  <span>Total spending</span>
                  <strong>
                    {getChangeText(
                      story.totalSpending,
                      "Total spending",
                      story.fromName,
                      story.toName
                    )}
                  </strong>
                  <em>{formatPercentChange(story.totalSpending.percentage_change)}</em>
                </div>
                <div
                  className={`cycle-comparison-summary-card tone-${story.remainingTone}`}
                >
                  <span>Remaining balance</span>
                  <strong>
                    {getChangeText(
                      story.remainingBalance,
                      "Remaining balance",
                      story.fromName,
                      story.toName
                    )}
                  </strong>
                  <em>{formatPercentChange(story.remainingBalance.percentage_change)}</em>
                </div>
                <div
                  className={`cycle-comparison-summary-card tone-${story.goalTone}`}
                >
                  <span>Goal contributions</span>
                  <strong>
                    {getChangeText(
                      story.goalContributions,
                      "Goal contributions",
                      story.fromName,
                      story.toName
                    )}
                  </strong>
                  <em>{formatPercentChange(story.goalContributions.percentage_change)}</em>
                </div>
                <div
                  className={`cycle-comparison-summary-card tone-${
                    story.biggestIncrease ? "negative" : "neutral"
                  }`}
                >
                  <span>Biggest increase</span>
                  <strong>
                    {story.biggestIncrease
                      ? getChangeText(
                          story.biggestIncrease,
                          "Total spending",
                          story.fromName,
                          story.toName,
                          formatSubcategoryName(story.biggestIncrease.name)
                        )
                      : "No increase"}
                  </strong>
                  <em>
                    {story.biggestIncrease
                      ? formatSignedEGP(story.biggestIncrease.difference)
                      : "Stable"}
                  </em>
                </div>
                <div
                  className={`cycle-comparison-summary-card tone-${
                    story.bestImprovement ? "positive" : "neutral"
                  }`}
                >
                  <span>Biggest reduction</span>
                  <strong>
                    {story.bestImprovement
                      ? getChangeText(
                          story.bestImprovement,
                          "Total spending",
                          story.fromName,
                          story.toName,
                          formatSubcategoryName(story.bestImprovement.name)
                        )
                      : "No reduction"}
                  </strong>
                  <em>
                    {story.bestImprovement
                      ? formatSignedEGP(story.bestImprovement.difference)
                      : "Stable"}
                  </em>
                </div>
              </div>

              <div className="cycle-health-panel">
                <div className="cycle-health-score-card">
                  <span>{story.fromName}</span>
                  <strong>{story.baseHealthScore} / 100</strong>
                </div>
                <div className="cycle-health-score-card is-current">
                  <span>{story.toName}</span>
                  <strong>{story.currentHealthScore} / 100</strong>
                </div>
                <div className="cycle-health-reasons">
                  <span>Financial health score</span>
                  {story.healthReasons.map((reason) => (
                    <p key={reason}>{reason}</p>
                  ))}
                </div>
              </div>

              <div className="cycle-comparison-chart">
                <div className="cycle-comparison-chart-legend">
                  <span>{story.fromName}</span>
                  <span>{story.toName}</span>
                </div>
                {metricRows.map(([label, row]) => {
                  const tone = getMeaningTone(row, label);

                  return (
                    <div className="cycle-comparison-chart-row" key={label}>
                      <div className="cycle-comparison-chart-row-heading">
                        <strong>{label}</strong>
                        <em className={`cycle-comparison-delta tone-${tone}`}>
                          {getChangeText(row, label, story.fromName, story.toName)}
                        </em>
                      </div>
                      <div className="cycle-comparison-bars">
                        <span
                          className="cycle-comparison-bar is-base"
                          style={{
                            width: `${Math.max(
                              4,
                              (Number(row.previous || 0) / chartMax) * 100
                            )}%`
                          }}
                        />
                        <span
                          className={`cycle-comparison-bar is-current tone-${tone}`}
                          style={{
                            width: `${Math.max(
                              4,
                              (Number(row.current || 0) / chartMax) * 100
                            )}%`
                          }}
                        />
                      </div>
                      <em className={`cycle-comparison-delta tone-${tone}`}>
                        {formatSignedEGP(row.difference)} - {formatPercentChange(row.percentage_change)}
                      </em>
                    </div>
                  );
                })}
              </div>

              <div className="cycle-highlight-grid">
                <div className="cycle-comparison-section">
                  <h3>Biggest increases</h3>
                  {story.categoryIncreases.length === 0 ? (
                    <p className="drawer-empty-text">No category increases.</p>
                  ) : (
                    story.categoryIncreases.slice(0, 3).map((row) => (
                      <div
                        className="cycle-comparison-mini-row tone-negative"
                        key={row.name}
                      >
                        <span>{row.name}</span>
                        <strong>
                          {getChangeText(
                            row,
                            "Total spending",
                            story.fromName,
                            story.toName,
                            row.name
                          )}
                        </strong>
                        <em>{formatPercentChange(row.percentage_change)}</em>
                      </div>
                    ))
                  )}
                </div>

                <div className="cycle-comparison-section">
                  <h3>Biggest reductions</h3>
                  {story.categoryReductions.length === 0 ? (
                    <p className="drawer-empty-text">No category reductions.</p>
                  ) : (
                    story.categoryReductions.slice(0, 3).map((row) => (
                      <div
                        className="cycle-comparison-mini-row tone-positive"
                        key={row.name}
                      >
                        <span>{row.name}</span>
                        <strong>
                          {getChangeText(
                            row,
                            "Total spending",
                            story.fromName,
                            story.toName,
                            row.name
                          )}
                        </strong>
                        <em>{formatPercentChange(row.percentage_change)}</em>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="cycle-comparison-section">
                <h3>Category changes</h3>
                {cycleComparison.categories.length === 0 ? (
                  <p className="drawer-empty-text">No category spending yet.</p>
                ) : (
                  cycleComparison.categories.slice(0, 8).map((row) => {
                    const tone = getMeaningTone(row, "Total spending");

                    return (
                      <div
                        className={`cycle-comparison-mini-row tone-${tone}`}
                        key={row.name}
                      >
                        <span>{row.name}</span>
                        <strong>
                          {getChangeText(
                            row,
                            "Total spending",
                            story.fromName,
                            story.toName,
                            row.name
                          )}
                        </strong>
                        <em>{formatPercentChange(row.percentage_change)}</em>
                      </div>
                    );
                  })
                )}
              </div>

              <div className="cycle-comparison-section">
                <h3>Subcategory insights</h3>
                {cycleComparison.subcategories.length === 0 ? (
                  <p className="drawer-empty-text">No subcategory spending yet.</p>
                ) : (
                  story.subcategoryInsights.slice(0, 10).map((row) => {
                    const tone = getMeaningTone(row, "Total spending");

                    return (
                      <div
                        className={`cycle-comparison-mini-row tone-${tone}`}
                        key={row.name}
                      >
                        <span>{formatSubcategoryName(row.name)}</span>
                        <strong>
                          {getChangeText(
                            row,
                            "Total spending",
                            story.fromName,
                            story.toName,
                            formatSubcategoryName(row.name)
                          )}
                        </strong>
                        <em>{formatPercentChange(row.percentage_change)}</em>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          );
        })()}
      </Modal>

      <Modal
        isOpen={Boolean(editingCycle)}
        onClose={() => {
          setEditingCycle(null);
          setEditingCycleName("");
        }}
        title="Edit Cycle Name"
      >
        {editingCycle && (
          <div className="cycle-edit-modal-content">
            <div className="cycle-edit-preview">
              <strong>{editingCycle.cycle_name || "Monthly Income"}</strong>
              <span>
                {formatCycleDate(editingCycle.start_date, {
                  month: "short",
                  day: "numeric"
                })}{" "}
                -{" "}
                {formatCycleDate(editingCycle.end_date, {
                  month: "short",
                  day: "numeric",
                  year: "numeric"
                })}
              </span>
            </div>
            <input
              className="expense-input"
              value={editingCycleName}
              onChange={(event) => setEditingCycleName(event.target.value)}
              placeholder="Cycle name"
            />
            <button
              className="primary-button"
              onClick={handleUpdateCycleName}
              disabled={cycleActionLoading}
            >
              Update Name
            </button>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={isGoalModalOpen}
        onClose={() => {
          if (goalLoading || confirmationRequest) return;
          setIsGoalModalOpen(false);
          resetGoalForm();
        }}
        title={editingGoal ? "Edit Goal" : "Create Goal"}
      >
        <div className="goal-modal-content">
          <div className="goal-modal-intro pulse-content-card">
            <div>
              <strong>Save with a clear purpose</strong>
              <p>
                Bako suggests a safe contribution from your current cycle
                while protecting the money you still need.
              </p>
            </div>
          </div>

          <GoalForm
            values={goalForm}
            onChange={handleGoalFieldChange}
            onSubmit={handleGoalSubmit}
            onDelete={editingGoal ? handleDeleteGoal : undefined}
            loading={goalLoading}
            submitLabel={editingGoal ? "Update Goal" : "Create Goal"}
          />
        </div>
      </Modal>

      <Modal
        isOpen={Boolean(contributionGoal)}
        onClose={() => {
          setContributionGoal(null);
          setContributionAmount("");
        }}
        title="Add Contribution"
      >
        {contributionGoal && (
          <div className="contribution-modal-content">
            <div className="goal-progress-card">
              <div className="goal-progress-header">
                <div>
                  <strong>{contributionGoal.name}</strong>
                  <span>
                    Remaining:{" "}
                    {formatEGP(
                      contributionGoal.target_amount -
                      contributionGoal.current_amount
                    )}
                  </span>
                </div>
              </div>
            </div>
            <input
              className="expense-input"
              type="number"
              min="0.01"
              step="0.01"
              placeholder="Contribution amount"
              value={contributionAmount}
              onChange={(event) => setContributionAmount(event.target.value)}
            />
            <button
              className="primary-button"
              onClick={handleContributeToGoal}
            >
              Add Contribution
            </button>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={isCycleModalOpen}
        onClose={() => setIsCycleModalOpen(false)}
        title="Create Financial Cycle"
      >
        <div className="setup-modal-content">
          <div className="drawer-section">
            <CycleForm
              cycleName={cycleName}
              setCycleName={setCycleName}
              income={income}
              setIncome={setIncome}
              startDate={startDate}
              setStartDate={setStartDate}
              endDate={endDate}
              setEndDate={setEndDate}
              handleCreateCycle={handleCreateCycle}
              cycleLoading={cycleLoading}
            />
          </div>
        </div>
      </Modal>

    </div>
  );
}

export default App;
