(function () {
  "use strict";

  const API_BASE = "/api/v1/runs";
  const EXCEPTIONS_API_BASE = "/api/v1/exceptions";
  const CAM_API_BASE = "/api/v1/cam-allocations";
  const CORRECTIONS_API_BASE = "/api/v1/data-corrections";
  const HR_API_BASE = "/api/v1/hr-reconciliation";
  // Tracks that the user has passed through HR reconciliation this session
  // so a reload goes back to Upload, not HR reconciliation.
  const HR_DONE_KEY = "sip_automation_hr_done";
  const PAGE_SIZE = 25;
  const STORAGE_KEY = "sip_automation_last_run";

  // Simple demo login gate: client-side only, any username accepted, one
  // shared password. No backend/session/API protection - this is purely a
  // UI gate for demo purposes, not real access control.
  const SHARED_PASSWORD = "sip2026";
  const AUTH_STORAGE_KEY = "sip_automation_authenticated";
  const USERNAME_STORAGE_KEY = "sip_automation_username";

  // Separate, extra password gate for Admin Settings - not every analyst
  // who can log in to the app should be able to open/edit these finance
  // parameters. Still client-side only / demo-level protection, same
  // caveats as the main login above.
  const ADMIN_PASSWORD = "finance2026";
  const ADMIN_AUTH_STORAGE_KEY = "sip_automation_admin_authenticated";
  const ADMIN_OPEN_KEY = "sip_automation_admin_open";
  const ADMIN_TAB_KEY = "sip_automation_admin_tab";

  // UI-only masking: these columns are still fetched from the backend (see
  // /results endpoint) but their values are never rendered in the table or
  // the "view full row" modal. This is a display-level mask, not a real
  // access control - the raw values are still present in the API response
  // and visible via browser dev tools/network tab to anyone using the page.
  const MASKED_COLUMNS = new Set([
    "Annual Salary (Payroll currency)",
    "Annual Salary (USD)",
    "YTD Salary (Payroll Currency)",
    "YTD Salary (USD)",
  ]);
  const MASK_TEXT = "•••••";

  // Admin Settings: DUMMY / demo only. These mirror the real
  // "FINANCE-CONTROLLED PARAMETERS" in config/calculations/sip_metrics.yaml,
  // grouped the same way. Editing them here is purely cosmetic - nothing is
  // sent to the backend and the real calculation config is never touched.
  const DEFAULT_PARAMETERS = {
    quarter: "Q4",

    q2_max_sip_multiplier: 0.5,
    q3_max_sip_multiplier: 0.75,
    q4_high_target_multiplier: 3.0,
    q4_high_target_threshold: 0.33,

    target_q2_multiplier: 0.5,
    target_q3_multiplier: 0.75,
    target_q4_multiplier: 1.0,

    revenue_incentive_weight: 0.65,
    gp_incentive_weight: 0.35,
    base_band_weight: 0.25,
    surge_band_weight: 0.75,
    base_achievement_band: 0.9,
    surge_achievement_band: 0.1,
    special_surge_revenue_cap: 0.05,
    special_surge_gp_floor: 0.0035,
    special_surge_gp_cap: 0.09,

    base_commission_threshold: 0.9,
    surge_commission_cap: 0.1,
    special_surge_threshold: 1.0,
  };

  const PARAMETER_GROUPS = [
    {
      title: "Quarter",
      keys: ["quarter"],
    },
    {
      title: "Maximum SIP rules",
      keys: [
        "q2_max_sip_multiplier",
        "q3_max_sip_multiplier",
        "q4_high_target_multiplier",
        "q4_high_target_threshold",
      ],
    },
    {
      title: "Target phasing (BP Revenue and GP/DOP)",
      keys: ["target_q2_multiplier", "target_q3_multiplier", "target_q4_multiplier"],
    },
    {
      title: "Commission rate weights",
      keys: [
        "revenue_incentive_weight",
        "gp_incentive_weight",
        "base_band_weight",
        "surge_band_weight",
        "base_achievement_band",
        "surge_achievement_band",
        "special_surge_revenue_cap",
        "special_surge_gp_floor",
        "special_surge_gp_cap",
      ],
    },
    {
      title: "Commission earning thresholds",
      keys: ["base_commission_threshold", "surge_commission_cap", "special_surge_threshold"],
    },
  ];

  const ADMIN_ROLES = [
    { value: "default", label: "Default (Global)" },
    { value: "sales_professional", label: "Sales Professional" },
    { value: "area_manager", label: "Area Manager" },
    { value: "district_manager", label: "District Manager" },
  ];

  // Parameters rendered as a <select> dropdown instead of a number input.
  const SELECT_PARAMETER_OPTIONS = {
    quarter: ["Q2", "Q3", "Q4"],
  };

  // Mirrors PRECOMPUTE_EXCEPTION_CATEGORIES in
  // src/sip_automation/core/precompute_exceptions.py. Used as a fallback if
  // GET /api/v1/exceptions/categories is unreachable; the live list from the
  // backend is preferred whenever available.
  const FALLBACK_EXCEPTION_CATEGORIES = [
    "Responsible for two groups",
    "Product Level targets",
    "Leave Case",
    "CS-IS Shipto Addition",
  ];
  const CUSTOM_CATEGORY_VALUE = "__custom__";

  // Per-role values, seeded from the live backend config when available, with
  // the old hardcoded defaults as an in-browser fallback. Lives only in memory
  // for this page load and is not persisted.
  const roleParameterState = {};
  let liveCalculationDefaults = null;

  function getDefaultParameterState() {
    return liveCalculationDefaults ? { ...liveCalculationDefaults } : { ...DEFAULT_PARAMETERS };
  }

  function getRoleParameters(role) {
    if (!roleParameterState[role]) {
      roleParameterState[role] = getDefaultParameterState();
    }
    return roleParameterState[role];
  }

  async function loadCalculationParameters() {
    try {
      const response = await fetch(`${API_BASE}/parameters`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }

      const data = await response.json();
      if (data && typeof data === "object") {
        liveCalculationDefaults = Object.fromEntries(
          Object.entries(data).filter(([, value]) => value !== null && value !== undefined)
        );

        Object.keys(roleParameterState).forEach((role) => {
          roleParameterState[role] = {
            ...getDefaultParameterState(),
            ...roleParameterState[role],
          };
        });
      }
    } catch (_err) {
      liveCalculationDefaults = null;
    }
  }

  // Shows which fiscal quarter/year calculations are currently running
  // against (config/calculations/sip_metrics.yaml parameters.quarter /
  // parameters.fiscal_year) - one global value, same for every run.
  // fiscal_year has no admin UI control (only "quarter" does - see
  // PARAMETER_GROUPS), so it's cached here to reuse when the badge needs
  // to be updated after an Apply that only changed the quarter.
  let calculationPeriodFiscalYear = null;

  async function loadCalculationPeriodBadge() {
    try {
      const response = await fetch(`${API_BASE}/parameters`, { cache: "no-store" });
      if (!response.ok) throw new Error(await readErrorDetail(response));

      const data = await response.json();
      const quarter = data && data.quarter;
      const fiscalYear = data && data.fiscal_year;

      if (quarter && fiscalYear) {
        calculationPeriodFiscalYear = fiscalYear;
        calculationPeriodBadge.textContent = `Running calculations for ${quarter} FY${fiscalYear}`;
        calculationPeriodBadge.hidden = false;
      } else {
        calculationPeriodBadge.hidden = true;
      }
    } catch (_err) {
      calculationPeriodBadge.hidden = true;
    }
  }

  function formatParameterLabel(key) {
    return key
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  // ---- DOM references ----
  const loginSection = document.getElementById("login-section");
  const loginForm = document.getElementById("login-form");
  const loginError = document.getElementById("login-error");
  const appShell = document.getElementById("app-shell");
  const logoutButton = document.getElementById("logout-button");
  const calculationPeriodBadge = document.getElementById("calculation-period-badge");

  const adminButton = document.getElementById("admin-button");
  const adminSection = document.getElementById("admin-section");
  const adminContentSection = document.getElementById("admin-content-section");
  const adminRoleSelect = document.getElementById("admin-role-select");
  const adminParameters = document.getElementById("admin-parameters");
  const adminResetButton = document.getElementById("admin-reset-button");
  const applyParametersButton = document.getElementById("apply-parameters-button");
  const parametersStatus = document.getElementById("parameters-status");
  const parametersError = document.getElementById("parameters-error");
  // adminBackButtonParam removed — replaced by single header back button
  const adminBackButton = document.getElementById("admin-back-button");

  const adminTabParametersButton = document.getElementById("admin-tab-parameters-button");
  const adminTabExceptionsButton = document.getElementById("admin-tab-exceptions-button");
  const adminParametersPanel = document.getElementById("admin-parameters-panel");
  const exceptionsPanel = document.getElementById("exceptions-panel");
  const exceptionsError = document.getElementById("exceptions-error");
  const exceptionsStatus = document.getElementById("exceptions-status");
  const exceptionsViewResultsButton = document.getElementById("exceptions-view-results-button");
  const exceptionsRecalculateButton = document.getElementById("exceptions-recalculate-button");
  const exceptionsUploadSummary = document.getElementById("exceptions-upload-summary");
  const exceptionsAddButton = document.getElementById("exceptions-add-button");
  const exceptionsUploadButton = document.getElementById("exceptions-upload-button");
  const exceptionsUploadInput = document.getElementById("exceptions-upload-input");
  const exceptionsTable = document.getElementById("exceptions-table");
  const exceptionsSearchInput = document.getElementById("exceptions-search-input");
  const exceptionsClearFiltersButton = document.getElementById("exceptions-clear-filters-button");
  const exceptionsFilterEmployeeId = document.getElementById("exceptions-filter-employee_id");
  const exceptionsFilterEmployeeName = document.getElementById("exceptions-filter-employee_name");
  const exceptionsFilterCategory = document.getElementById("exceptions-filter-category");
  const exceptionsFilterMonthsEligible = document.getElementById("exceptions-filter-months_eligible_override");
  const exceptionsFilterBpRev = document.getElementById("exceptions-filter-bp_fy26_rev");
  const exceptionsFilterBpGp = document.getElementById("exceptions-filter-bp_fy26_gp");
  const exceptionsFilterYtdRev = document.getElementById("exceptions-filter-ytd_fy26_rev");
  const exceptionsFilterYtdGp = document.getElementById("exceptions-filter-ytd_fy26_gp");
  const exceptionsFilterYtdActualRevenue = document.getElementById("exceptions-filter-ytd_actual_revenue_override");
  const exceptionsFilterYtdActualGpDop = document.getElementById("exceptions-filter-ytd_actual_gp_dop_override");
  const exceptionsFilterBpSga = document.getElementById("exceptions-filter-bp_sga");
  const exceptionsFilterYtdSga = document.getElementById("exceptions-filter-ytd_sga");

  const exceptionsPendingDeletePanel = document.getElementById("exceptions-pending-delete-panel");
  const exceptionsPendingDeleteCount = document.getElementById("exceptions-pending-delete-count");
  const exceptionsPendingDeleteList = document.getElementById("exceptions-pending-delete-list");
  const exceptionsApplyDeletionsButton = document.getElementById("exceptions-apply-deletions-button");
  const exceptionsCancelDeletionsButton = document.getElementById("exceptions-cancel-deletions-button");

  const exceptionModal = document.getElementById("exception-modal");
  const exceptionModalTitle = document.getElementById("exception-modal-title");
  const exceptionModalCloseButton = document.getElementById("exception-modal-close-button");
  const exceptionForm = document.getElementById("exception-form");
  const exceptionFormError = document.getElementById("exception-form-error");
  const exceptionFormCancelButton = document.getElementById("exception-form-cancel-button");
  const exceptionEmployeeIdInput = document.getElementById("exception-employee-id");
  const exceptionEmployeeNameInput = document.getElementById("exception-employee-name");
  const exceptionCategorySelect = document.getElementById("exception-category-select");
  const exceptionCategoryCustomField = document.getElementById("exception-category-custom-field");
  const exceptionCategoryCustomInput = document.getElementById("exception-category-custom");
  const exceptionBpRevInput = document.getElementById("exception-bp-rev");
  const exceptionBpRevPercentageInput = document.getElementById("exception-bp-rev-percentage");
  const exceptionBpRevDirectionSelect = document.getElementById("exception-bp-rev-direction");

  const exceptionBpGpInput = document.getElementById("exception-bp-gp");
  const exceptionBpGpPercentageInput = document.getElementById("exception-bp-gp-percentage");
  const exceptionBpGpDirectionSelect = document.getElementById("exception-bp-gp-direction");

  const exceptionYtdRevInput = document.getElementById("exception-ytd-rev");
  const exceptionYtdRevPercentageInput = document.getElementById("exception-ytd-rev-percentage");
  const exceptionYtdRevDirectionSelect = document.getElementById("exception-ytd-rev-direction");

  const exceptionYtdGpInput = document.getElementById("exception-ytd-gp");
  const exceptionYtdGpPercentageInput = document.getElementById("exception-ytd-gp-percentage");
  const exceptionYtdGpDirectionSelect = document.getElementById("exception-ytd-gp-direction");

  const exceptionMonthsEligibleOverrideInput = document.getElementById("exception-months-eligible-override");
  const exceptionYtdActualRevenueOverrideInput = document.getElementById("exception-ytd-actual-revenue-override");
  const exceptionYtdActualGpDopOverrideInput = document.getElementById("exception-ytd-actual-gp-dop-override");
  const exceptionTargetSalesRevDirectOverrideInput = document.getElementById("exception-target-sales-rev-direct-override");
  const exceptionTargetGpDopDirectOverrideInput = document.getElementById("exception-target-gp-dop-direct-override");
  const exceptionBpSgaInput = document.getElementById("exception-bp-sga");
  const exceptionYtdSgaInput = document.getElementById("exception-ytd-sga");

  // Config-driven list of the complete-override fields: a single value
  // that replaces the calculated metric outright (no percentage/direction).
  const EXCEPTION_OVERRIDE_FIELDS = [
    {
      key: "months_eligible_override",
      valueInput: exceptionMonthsEligibleOverrideInput,
    },
    {
      key: "ytd_actual_revenue_override",
      valueInput: exceptionYtdActualRevenueOverrideInput,
    },
    {
      key: "ytd_actual_gp_dop_override",
      valueInput: exceptionYtdActualGpDopOverrideInput,
    },
    {
      key: "target_sales_rev_direct_override",
      valueInput: exceptionTargetSalesRevDirectOverrideInput,
    },
    {
      key: "target_gp_dop_direct_override",
      valueInput: exceptionTargetGpDopDirectOverrideInput,
    },
  ];

  // Config-driven list of the 2 SG&A subtraction fields: a single value
  // subtracted from Target GP/DOP DIRECT / YTD Actual GP/DOP when entered
  // (no percentage/direction, same shape as EXCEPTION_OVERRIDE_FIELDS).
  const EXCEPTION_SGA_FIELDS = [
    {
      key: "bp_sga",
      valueInput: exceptionBpSgaInput,
    },
    {
      key: "ytd_sga",
      valueInput: exceptionYtdSgaInput,
    },
  ];

  // Config-driven list of the 4 amount fields, each with its own amount /
  // percentage / direction inputs and matching API field names. Used to
  // avoid repeating the same read/write logic 4 times.
  const EXCEPTION_AMOUNT_FIELDS = [
    {
      key: "bp_fy26_rev",
      amountInput: exceptionBpRevInput,
      percentageInput: exceptionBpRevPercentageInput,
      directionSelect: exceptionBpRevDirectionSelect,
    },
    {
      key: "bp_fy26_gp",
      amountInput: exceptionBpGpInput,
      percentageInput: exceptionBpGpPercentageInput,
      directionSelect: exceptionBpGpDirectionSelect,
    },
    {
      key: "ytd_fy26_rev",
      amountInput: exceptionYtdRevInput,
      percentageInput: exceptionYtdRevPercentageInput,
      directionSelect: exceptionYtdRevDirectionSelect,
    },
    {
      key: "ytd_fy26_gp",
      amountInput: exceptionYtdGpInput,
      percentageInput: exceptionYtdGpPercentageInput,
      directionSelect: exceptionYtdGpDirectionSelect,
    },
  ];

  const adminPasswordSection = document.getElementById("admin-password-section");
  const adminPasswordForm = document.getElementById("admin-password-form");
  const adminPasswordError = document.getElementById("admin-password-error");
  const adminPasswordCancelButton = document.getElementById("admin-password-cancel-button");

  const uploadSection = document.getElementById("upload-section");
  const uploadForm = document.getElementById("upload-form");
  const uploadError = document.getElementById("upload-error");
  const runButton = document.getElementById("run-button");

  const progressSection = document.getElementById("progress-section");
  const progressFill = document.getElementById("progress-fill");
  const progressError = document.getElementById("progress-error");
  const startOverButton = document.getElementById("start-over-button");
  const steps = Array.from(document.querySelectorAll(".step"));

  const resultsSection = document.getElementById("results-section");
  const roleSelect = document.getElementById("role-select");
  const searchInput = document.getElementById("search-input");
  const downloadLink = document.getElementById("download-link");
  const resultsSummary = document.getElementById("results-summary");
  const resultsTable = document.getElementById("results-table");
  const resultsEmptyState = document.getElementById("results-empty-state");
  const prevPageButton = document.getElementById("prev-page-button");
  const nextPageButton = document.getElementById("next-page-button");
  const pageIndicator = document.getElementById("page-indicator");

  const rowModal = document.getElementById("row-modal");
  const modalBody = document.getElementById("modal-body");
  const modalCloseButton = document.getElementById("modal-close-button");
  const newRunButton = document.getElementById("new-run-button");

  const adminTabCorrectionsButton = document.getElementById("admin-tab-corrections-button");
  const correctionsPanel = document.getElementById("corrections-panel");
  const correctionsError = document.getElementById("corrections-error");
  const correctionsStatus = document.getElementById("corrections-status");
  const correctionsAddButton = document.getElementById("corrections-add-button");
  const correctionsApplyAllButton = document.getElementById("corrections-apply-all-button");
  const correctionsViewResultsButton = document.getElementById("corrections-view-results-button");
  const correctionsTable = document.getElementById("corrections-table");

  const correctionModal = document.getElementById("correction-modal");
  const correctionModalTitle = document.getElementById("correction-modal-title");

  const adminTabCamButton = document.getElementById("admin-tab-cam-button");
  const adminTabHrExclusionsButton = document.getElementById("admin-tab-hr-exclusions-button");
  const camPanel = document.getElementById("cam-panel");
  const hrExclusionsPanel = document.getElementById("hr-exclusions-panel");
  const hrExclError = document.getElementById("hr-excl-error");
  const hrExclStatus = document.getElementById("hr-excl-status");
  const hrExclAddButton = document.getElementById("hr-excl-add-button");
  const hrExclSearchInput = document.getElementById("hr-excl-search-input");
  const hrExclList = document.getElementById("hr-excl-list");
  const hrExclEmpty = document.getElementById("hr-excl-empty");
  const hrExclRecalcButton = document.getElementById("hr-excl-recalc-button");
  const hrExclViewResultsButton = document.getElementById("hr-excl-view-results-button");
  const camError = document.getElementById("cam-error");
  const camStatus = document.getElementById("cam-status");
  const camViewResultsButton = document.getElementById("cam-view-results-button");
  const camAddButton = document.getElementById("cam-add-button");
  const camDivisionTotalsWarning = document.getElementById("cam-division-totals-warning");
  const camSearchInput = document.getElementById("cam-search-input");
  const camTable = document.getElementById("cam-table");
  const camPendingHint = document.getElementById("cam-pending-hint");
  const camApplyAllButton = document.getElementById("cam-apply-all-button");
  const camDiscardButton = document.getElementById("cam-discard-button");
  const camModal = document.getElementById("cam-modal");
  const camModalTitle = document.getElementById("cam-modal-title");
  const camModalClose = document.getElementById("cam-modal-close");
  const camForm = document.getElementById("cam-form");
  const camFormError = document.getElementById("cam-form-error");
  const camFormCancel = document.getElementById("cam-form-cancel");
  const camCamIdInput = document.getElementById("cam-cam-id");
  const camEmployeeNameInput = document.getElementById("cam-employee-name");
  const camDivisionNodeInput = document.getElementById("cam-division-node");
  const camPctRevInput = document.getElementById("cam-pct-rev");
  const camPctGpInput = document.getElementById("cam-pct-gp");
  const camNoteInput = document.getElementById("cam-note");
  const correctionModalClose = document.getElementById("correction-modal-close");
  const correctionForm = document.getElementById("correction-form");
  const correctionFormError = document.getElementById("correction-form-error");
  const correctionFormCancel = document.getElementById("correction-form-cancel");
  const correctionEmployeeIdInput = document.getElementById("correction-employee-id");
  const correctionEmployeeNameInput = document.getElementById("correction-employee-name");
  const correctionSourceFileSelect = document.getElementById("correction-source-file");
  const correctionColumnNameInput = document.getElementById("correction-column-name");
  const correctionColumnNameSelect = document.getElementById("correction-column-name-select");
  const correctionNewValueInput = document.getElementById("correction-new-value");
  const correctionNoteInput = document.getElementById("correction-note");

  // ---- HR Reconciliation DOM refs ----
  const hrReconciliationSection = document.getElementById("hr-reconciliation-section");
  const hrQ1FileInput = document.getElementById("hr-q1-file");
  const hrQ2FileInput = document.getElementById("hr-q2-file");
  const hrCompareButton = document.getElementById("hr-compare-button");
  const hrReconError = document.getElementById("hr-recon-error");
  const hrDiffSection = document.getElementById("hr-diff-section");
  const hrSummaryBar = document.getElementById("hr-summary-bar");
  const hrDiffTable = document.getElementById("hr-diff-table");
  const hrExcludeAll = document.getElementById("hr-exclude-all");
  const hrExcludeHint = document.getElementById("hr-exclude-hint");
  const hrFilterNewJoiners = document.getElementById("hr-filter-new-joiners");
  const hrFilterLeavers = document.getElementById("hr-filter-leavers");
  const hrFilterChanges = document.getElementById("hr-filter-changes");
  const hrExportButton = document.getElementById("hr-export-button");
  const hrSavedExclusions = document.getElementById("hr-saved-exclusions");
  const hrSavedList = document.getElementById("hr-saved-list");
  const hrConfirmButton = document.getElementById("hr-confirm-button");
  const hrSkipButton = document.getElementById("hr-skip-button");

  // ---- State ----
  let currentRunId = null;
  let currentColumns = [];
  let curatedColumns = [];
  let allRows = [];
  let filteredRows = [];
  let currentPage = 1;
  let currentResultsLabel = "all roles";
  // Per-column dropdown filters: { columnName: "selected value" }. An empty
  // string (or missing key) means "All" - no filter applied for that column.
  let columnFilters = {};

  // ---- HR Reconciliation state ----
  let hrAllChanges = [];        // full diff from /compare
  let hrVisibleChanges = [];    // filtered by checkboxes
  let hrExcludedIds = new Set(); // employee IDs checked for exclusion

  // ---- CAM Allocations state ----
  let currentCamOverrides = [];
  let editingCamOverrideId = null;

  let hrExclusions = [];    // current list of excluded employee IDs
  // True once an exclusion has been added/removed since the last load or
  // successful recalculate - i.e. there's actually something new for
  // Recalculate to apply. Without this, Recalculate showed just because a
  // run existed, even with zero pending changes (see updateCorrectionsApplyButtonVisibility
  // above for the same "only show when there's something to apply" pattern).
  let hrExclusionsDirty = false;

  // ---- Data Corrections state ----
  let currentCorrections = [];
  let editingCorrectionId = null;
  let correctionFileOptions = {};
  // Deleting a correction doesn't touch canonical data by itself (see the
  // DELETE endpoint) - canonical still reflects the old value until "Apply
  // All Changes" rebuilds it. currentCorrections.length alone can't signal
  // that once the LAST correction is deleted (list goes to 0, but a rebuild
  // is still needed to remove its effect) - hence this separate flag, reset
  // once that rebuild actually runs.
  let correctionsDeletionPending = false;

  // ---- Precompute Exceptions state ----
  let exceptionCategories = FALLBACK_EXCEPTION_CATEGORIES;
  function makeDefaultExceptionsColumnFilters() {
    return {
      employee_id: "",
      employee_name: "",
      category: "",
      months_eligible_override: "",
      bp_fy26_rev: "",
      bp_fy26_gp: "",
      ytd_fy26_rev: "",
      ytd_fy26_gp: "",
      ytd_actual_revenue_override: "",
      ytd_actual_gp_dop_override: "",
      bp_sga: "",
      ytd_sga: "",
    };
  }

  let currentExceptions = [];
  let exceptionsSearchTerm = "";
  let exceptionsColumnFilters = makeDefaultExceptionsColumnFilters();
  let editingExceptionId = null;

  // Exceptions staged for deletion but not yet actually deleted - lets an
  // admin queue up several deletes, review them, and apply them (and
  // recalculate) all at once instead of once per click. Keyed by exception id.
  let exceptionsPendingDeleteIds = new Set();
  // Employee IDs (or upload summaries) changed via Save/Upload since the
  // last successful recalculate - shown in the status banner so nothing
  // gets lost track of if several exceptions are edited before clicking
  // "Recalculate Now". A JS Set preserves insertion order, so the banner
  // lists changes in the order they were made.
  let exceptionsPendingRecalcNotes = new Set();

  // ---- Section visibility ----
  // Single source of truth for "only one main section visible at a time".
  // Every show*Section() function below calls this first, then unhides
  // exactly the one section it wants. This guards against the class of bug
  // where two sections both end up visible because some code path forgot to
  // hide one of them (e.g. upload-section has no `hidden` attribute in the
  // HTML by default, so anything that skips hiding it explicitly leaves it
  // visible alongside whatever else is shown).
  function hideAllMainSections() {
    // Main navigable sections
    hrReconciliationSection.hidden = true;
    hrExclusionsPanel.hidden = true;
    adminPasswordSection.hidden = true;
    adminSection.hidden = true;
    adminContentSection.hidden = true;
    uploadSection.hidden = true;
    progressSection.hidden = true;
    resultsSection.hidden = true;
    // The Precompute Exceptions tab widens #admin-content-section (see
    // showAdminTab) - clear that here so switching to any other section/tab
    // never inherits the extra width.
    adminContentSection.classList.remove("admin-content--wide-exceptions");
    // Close any open modals so they don't float over the new section
    rowModal.hidden = true;
    exceptionModal.hidden = true;
    correctionModal.hidden = true;
    camModal.hidden = true;
  }

  // ---- Stepper helpers ----
  function setStep(stepNumber, state) {
    const step = steps.find((el) => el.dataset.step === String(stepNumber));
    if (!step) return;
    step.classList.remove("active", "done", "error");
    if (state) step.classList.add(state);
  }

  function setProgress(percent) {
    progressFill.style.width = percent + "%";
  }

  async function readErrorDetail(response) {
    try {
      const body = await response.json();
      return body.detail || `Request failed with status ${response.status}.`;
    } catch (_err) {
      return `Request failed with status ${response.status}.`;
    }
  }

  function showProgressError(message) {
    progressError.textContent = message;
    progressError.hidden = false;
    startOverButton.hidden = false;
  }

  function resetUI() {
    currentRunId = null;
    currentColumns = [];
    curatedColumns = [];
    allRows = [];
    filteredRows = [];
    currentPage = 1;

    uploadForm.reset();
    uploadError.hidden = true;

    progressError.hidden = true;
    startOverButton.hidden = true;
    setProgress(0);
    progressFill.classList.remove("loading");
    steps.forEach((step) => step.classList.remove("active", "done", "error"));

    hideAllMainSections();
    uploadSection.hidden = false;
    runButton.disabled = false;
  }

  // Full reset used when the user explicitly wants to start a brand-new
  // run (Start Over / Start New Run) - clears the persisted run too, unlike
  // a plain resetUI() (used e.g. on logout, where we want the previous run
  // to still be there on next login).
  function resetUIForNewRun() {
    resetUI();
    clearPersistedRun();
    sessionStorage.removeItem(HR_DONE_KEY);
    // Route back through HR reconciliation so user can update exclusions.
    uploadSection.hidden = true;
    showHrSection();
  }

  // ---- Persist the completed run across page reloads (sessionStorage) ----
  // Only the run_id + role list are stored, not the actual result rows -
  // those are re-fetched from /results on restore, same as a normal load.
  function persistRun(runId, enabledRoles, roleRowCounts) {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ runId, enabledRoles, roleRowCounts })
      );
    } catch (_err) {
      // sessionStorage unavailable (e.g. private browsing) - reload
      // simply won't restore results in that case, nothing else to do.
    }
  }

  function clearPersistedRun() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (_err) {
      // ignore
    }
  }

  function readPersistedRun() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_err) {
      return null;
    }
  }

  async function fetchServerCurrentRun() {
    try {
      const response = await fetch(`${API_BASE}/current`, { cache: "no-store" });
      if (!response.ok) return null;

      const data = await response.json();
      if (!data.run_id) return null;

      return {
        runId: data.run_id,
        enabledRoles: data.enabled_roles || [],
        roleRowCounts: data.role_row_counts || {},
      };
    } catch (_err) {
      return null;
    }
  }

  async function restorePersistedRunIfAny() {
    // Server-side pointer (data/current_run.yaml) is the source of truth -
    // it survives a full browser restart, not just a logout within the
    // same tab. Only fall back to the local sessionStorage pointer if the
    // server request itself fails (e.g. server temporarily unreachable).
    const saved = (await fetchServerCurrentRun()) || readPersistedRun();
    if (!saved || !saved.runId) return false;

    currentRunId = saved.runId;
    populateRoleSelect(saved.enabledRoles, saved.roleRowCounts);

    hideAllMainSections();

    try {
      await loadResults(roleSelect.value);
      resultsSection.hidden = false;
      persistRun(saved.runId, saved.enabledRoles, saved.roleRowCounts);
      return true;
    } catch (_err) {
      // Result files are gone (e.g. server restarted) — go to upload form,
      // not HR reconciliation. HR is only for an intentional new-run start.
      currentRunId = null;
      clearPersistedRun();
      hideAllMainSections();
      uploadSection.hidden = false;
      return true; // already handled navigation
    }
  }

  // ---- Pipeline orchestration ----
  uploadForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    uploadError.hidden = true;

    const files = {
      employee_file: document.getElementById("employee_file").files[0],
      bp_file: document.getElementById("bp_file").files[0],
      sales_file: document.getElementById("sales_file").files[0],
      nacs_guarantee_file: document.getElementById("nacs_guarantee_file").files[0],
      ytd_payments_file: document.getElementById("ytd_payments_file").files[0],
      bdm_file: document.getElementById("bdm_file").files[0],
    };

    if (!Object.values(files).some(Boolean)) {
      uploadError.textContent = "Please choose at least one file to upload.";
      uploadError.hidden = false;
      return;
    }

    runButton.disabled = true;
    hideAllMainSections();
    progressSection.hidden = false;
    progressError.hidden = true;
    startOverButton.hidden = true;
    setProgress(0);
    // Animate the bar continuously while any stage is in flight, since a
    // single stage can take a while and a static bar looks frozen/dead.
    progressFill.classList.add("loading");

    try {
      // Stage 1: upload + raw load
      setStep(1, "active");
      setProgress(6); // small visible sliver so the bar isn't 0-width/invisible while this (often long) stage runs
      const formData = new FormData();
      for (const [field, file] of Object.entries(files)) {
        if (file) {
          formData.append(field, file);
        }
      }

      const rawLoadResponse = await fetch(API_BASE, {
        method: "POST",
        body: formData,
      });

      if (!rawLoadResponse.ok) {
        setStep(1, "error");
        throw new Error(await readErrorDetail(rawLoadResponse));
      }

      const rawLoadResult = await rawLoadResponse.json();
      currentRunId = rawLoadResult.run_id;
      setStep(1, "done");
      setProgress(25);

      // Stage 2: canonical
      setStep(2, "active");
      setProgress(30);
      const canonicalResponse = await fetch(`${API_BASE}/${currentRunId}/canonical`, {
        method: "POST",
      });

      if (!canonicalResponse.ok) {
        setStep(2, "error");
        throw new Error(await readErrorDetail(canonicalResponse));
      }

      setStep(2, "done");
      setProgress(50);

      // Stage 3: calculations
      setStep(3, "active");
      setProgress(55);
      const calculationParams = getCalculationParameters("default");
      const calculationsResponse = await fetch(`${API_BASE}/${currentRunId}/calculations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(calculationParams),
      });

      if (!calculationsResponse.ok) {
        setStep(3, "error");
        throw new Error(await readErrorDetail(calculationsResponse));
      }

      const calculationsResult = await calculationsResponse.json();
      setStep(3, "done");
      setProgress(75);

      // Stage 4: load results
      setStep(4, "active");
      setProgress(80);
      populateRoleSelect(calculationsResult.enabled_roles, calculationsResult.role_row_counts);
      await loadResults(roleSelect.value);
      setStep(4, "done");
      setProgress(100);
      progressFill.classList.remove("loading");

      persistRun(
        currentRunId,
        calculationsResult.enabled_roles,
        calculationsResult.role_row_counts
      );

      resultsSection.hidden = false;
    } catch (err) {
      progressFill.classList.remove("loading");
      showProgressError(err.message || String(err));
    }
  });

  function confirmAndResetUIForNewRun() {
    const confirmed = window.confirm(
      "Starting a new run will take you away from the current run's results. " +
        "You can still reach the old run's output files on disk, but you won't " +
        "be able to get back to them from this screen. Continue?"
    );

    if (!confirmed) return;

    resetUIForNewRun();
  }

  startOverButton.addEventListener("click", confirmAndResetUIForNewRun);
  newRunButton.addEventListener("click", confirmAndResetUIForNewRun);

  // ---- Results: role select / load ----
  function populateRoleSelect(enabledRoles, roleRowCounts) {
    roleSelect.innerHTML = "";

    const allOption = document.createElement("option");
    allOption.value = "all";
    allOption.textContent = "All roles";
    roleSelect.appendChild(allOption);

    (enabledRoles || []).forEach((role) => {
      const option = document.createElement("option");
      option.value = role;
      const count = roleRowCounts && roleRowCounts[role] !== undefined ? ` (${roleRowCounts[role]})` : "";
      option.textContent = role + count;
      roleSelect.appendChild(option);
    });
  }

  roleSelect.addEventListener("change", async function () {
    loadResults(roleSelect.value);
  });

  searchInput.addEventListener("input", function () {
    currentPage = 1;
    applyFilter();
    renderTable();
  });

  async function loadResults(role) {
    // no-store: results change after every recalculation and must never be
    // served from the browser's cache under the same URL.
    const response = await fetch(`${API_BASE}/${currentRunId}/results?role=${encodeURIComponent(role)}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      const detail = await readErrorDetail(response);
      resultsSummary.textContent = detail;
      allRows = [];
      filteredRows = [];
      currentColumns = [];
      curatedColumns = [];
      renderTable();
      return;
    }

    const data = await response.json();
    currentColumns = data.columns;
    curatedColumns = data.curated_columns.length ? data.curated_columns : data.columns.slice(0, 8);
    allRows = data.rows;
    filteredRows = allRows;
    currentResultsLabel = role === "all" ? "all roles" : role;
    currentPage = 1;
    columnFilters = {};

    resultsSummary.textContent = `${data.row_count} row(s) for ${role === "all" ? "all roles" : role}.`;
    downloadLink.href = `${API_BASE}/${currentRunId}/results/download?role=${encodeURIComponent(role)}`;

    searchInput.value = "";
    renderTableHeader();
    renderTable();
  }

  // Display-only formatting: cap decimals at 2 places, and mask sensitive
  // salary columns. Backend/raw data is untouched — this only affects what's
  // rendered in the table/modal.
  function formatValue(value, column) {
    if (column && MASKED_COLUMNS.has(column)) return MASK_TEXT;
    if (value === null || value === undefined) return "";
    if (typeof value === "number") {
      return Number.isInteger(value) ? String(value) : value.toFixed(2);
    }
    return value;
  }

  // Only these columns get an in-header filter dropdown - the rest are
  // either unique-per-row (Employee ID, Preferred Name) or continuous
  // numeric values (SIP Target, YTD SIP Earned), where a dropdown of every
  // distinct value isn't a meaningful filter.
  const FILTERABLE_COLUMNS = new Set([
    "Employee ID",
    "Position",
    "Sales Office Description",
    "Sales Group Description",
    "Flag",
  ]);

  function applyFilter() {
    const term = searchInput.value.trim().toLowerCase();

    filteredRows = allRows.filter((row) => {
      const matchesColumnFilters = curatedColumns.every((column) => {
        const selected = columnFilters[column];
        if (!selected) return true;
        return formatValue(row[column], column) === selected;
      });
      if (!matchesColumnFilters) return false;

      if (!term) return true;
      return curatedColumns.some((column) => String(row[column] ?? "").toLowerCase().includes(term));
    });
  }

  function renderTableHeader() {
    const thead = resultsTable.querySelector("thead");
    thead.innerHTML = "";
    const headerRow = document.createElement("tr");

    curatedColumns.forEach((column) => {
      const th = document.createElement("th");

      const label = document.createElement("div");
      label.className = "th-label";
      label.textContent = column;
      th.appendChild(label);

      if (FILTERABLE_COLUMNS.has(column) && !MASKED_COLUMNS.has(column)) {
        th.appendChild(buildColumnFilterSelect(column));
      }

      headerRow.appendChild(th);
    });

    const actionTh = document.createElement("th");
    actionTh.textContent = "";
    headerRow.appendChild(actionTh);

    thead.appendChild(headerRow);
  }

  // Dropdown populated with the distinct values present in the currently
  // loaded rows (rebuilt whenever roles/results change, so options always
  // match what's actually on screen).
  function buildColumnFilterSelect(column) {
    const values = Array.from(
      new Set(allRows.map((row) => formatValue(row[column], column)).filter((v) => v !== ""))
    ).sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));

    const select = document.createElement("select");
    select.className = "th-filter";

    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "All";
    select.appendChild(allOption);

    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });

    select.value = columnFilters[column] || "";
    select.addEventListener("click", function (event) {
      event.stopPropagation();
    });
    select.addEventListener("change", function () {
      columnFilters[column] = select.value;
      currentPage = 1;
      applyFilter();
      renderTable();
    });

    return select;
  }

  function renderTable() {
    const tbody = resultsTable.querySelector("tbody");
    tbody.innerHTML = "";

    if (filteredRows.length === 0) {
      resultsEmptyState.hidden = false;
      resultsSummary.textContent = allRows.length
        ? "No matching records found."
        : `No records found for ${currentResultsLabel}.`;
      pageIndicator.textContent = "Page 0 of 0";
      prevPageButton.disabled = true;
      nextPageButton.disabled = true;
      return;
    }

    resultsEmptyState.hidden = true;
    resultsSummary.textContent =
      filteredRows.length === allRows.length
        ? `${allRows.length} row(s) for ${currentResultsLabel}.`
        : `${filteredRows.length} matching row(s) of ${allRows.length}.`;

    const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
    currentPage = Math.min(currentPage, totalPages);

    const start = (currentPage - 1) * PAGE_SIZE;
    const pageRows = filteredRows.slice(start, start + PAGE_SIZE);

    pageRows.forEach((row) => {
      const tr = document.createElement("tr");

      curatedColumns.forEach((column) => {
        const td = document.createElement("td");
        td.textContent = formatValue(row[column], column);
        tr.appendChild(td);
      });

      const actionTd = document.createElement("td");
      const viewButton = document.createElement("button");
      viewButton.type = "button";
      viewButton.className = "btn btn-secondary";
      viewButton.textContent = "View";
      viewButton.addEventListener("click", () => openRowModal(row));
      actionTd.appendChild(viewButton);
      tr.appendChild(actionTd);

      tbody.appendChild(tr);
    });

    pageIndicator.textContent = `Page ${currentPage} of ${totalPages}`;
    prevPageButton.disabled = currentPage <= 1;
    nextPageButton.disabled = currentPage >= totalPages;
  }

  prevPageButton.addEventListener("click", function () {
    currentPage -= 1;
    renderTable();
  });

  nextPageButton.addEventListener("click", function () {
    currentPage += 1;
    renderTable();
  });

  function openRowModal(row) {
    modalBody.innerHTML = "";

    // Render as two side-by-side label:value pairs per visual row instead
    // of one long single-column list, so ~60 fields take ~30 rows of
    // scrolling instead of ~60 - easier to scan/correlate without as much
    // scrolling. Works with the 4-column grid defined in styles.css
    // (label | value | label | value).
    currentColumns.forEach((column) => {
      const dt = document.createElement("dt");
      dt.textContent = column;
      const dd = document.createElement("dd");
      dd.textContent = formatValue(row[column], column);
      modalBody.appendChild(dt);
      modalBody.appendChild(dd);
    });

    rowModal.hidden = false;
  }

  modalCloseButton.addEventListener("click", function () {
    rowModal.hidden = true;
  });

  rowModal.addEventListener("click", function (event) {
    if (event.target === rowModal) rowModal.hidden = true;
  });

  // ---- HR Reconciliation ----

  async function showHrSection() {
    hideAllMainSections();
    hrAllChanges = [];
    hrVisibleChanges = [];
    hrExcludedIds = new Set();
    hrReconError.hidden = true;
    hrDiffSection.hidden = true;
    hrConfirmButton.hidden = true;
    hrQ1FileInput.value = "";
    hrQ2FileInput.value = "";
    hrExcludeAll.checked = false;
    hrReconciliationSection.hidden = false;

    // Show currently saved exclusions as removable chips.
    try {
      const resp = await fetch(`${HR_API_BASE}/exclusions`, { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        const ids = data.excluded_employee_ids || [];
        if (ids.length > 0) {
          hrSavedList.innerHTML = "";
          ids.forEach((empId) => {
            const chip = document.createElement("span");
            chip.className = "hr-exclusion-chip";
            chip.textContent = empId;
            const removeBtn = document.createElement("button");
            removeBtn.type = "button";
            removeBtn.textContent = "Include Back";
            removeBtn.title = "Remove from exclusions and include in calculations";
            removeBtn.style.cssText = "margin-left:8px;padding:2px 7px;font-size:11px;border-radius:10px;border:1px solid #888;background:#fff;color:#333;cursor:pointer;";
            removeBtn.addEventListener("click", async function () {
              // Remove this ID from the saved list immediately
              const newResp = await fetch(`${HR_API_BASE}/exclusions`, { cache: "no-store" });
              if (!newResp.ok) return;
              const newData = await newResp.json();
              const newIds = (newData.excluded_employee_ids || []).filter((id) => id !== empId);
              await fetch(`${HR_API_BASE}/exclusions`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ excluded_employee_ids: newIds }),
              });
              chip.remove();
              if (hrSavedList.children.length === 0) hrSavedExclusions.hidden = true;
            });
            chip.appendChild(removeBtn);
            hrSavedList.appendChild(chip);
          });
          hrSavedExclusions.hidden = false;
        } else {
          hrSavedExclusions.hidden = true;
        }
      }
    } catch (_err) {
      hrSavedExclusions.hidden = true;
    }
  }

  hrCompareButton.addEventListener("click", async function () {
    const q1 = hrQ1FileInput.files[0];
    const q2 = hrQ2FileInput.files[0];

    if (!q1 || !q2) {
      hrReconError.textContent = "Please select both Q1 and Q2 HR files before comparing.";
      hrReconError.hidden = false;
      return;
    }

    hrReconError.hidden = true;
    hrCompareButton.disabled = true;
    hrCompareButton.textContent = "Comparing…";
    hrDiffSection.hidden = true;

    try {
      const formData = new FormData();
      formData.append("q1_file", q1);
      formData.append("q2_file", q2);

      const resp = await fetch(`${HR_API_BASE}/compare`, { method: "POST", body: formData });
      if (!resp.ok) {
        throw new Error(await readErrorDetail(resp));
      }

      const data = await resp.json();
      hrAllChanges = data.changes || [];
      // Pre-select ALL employees with changes for exclusion — the typical
      // workflow is to exclude changed employees from calculations until
      // changes are reviewed. Users can uncheck any they want to keep in.
      hrExcludedIds = new Set(hrAllChanges.map((c) => c.employee_id));

      // Render summary bar
      const s = data.summary || {};
      hrSummaryBar.innerHTML =
        `<span class="hr-badge hr-badge-new">New Joiners: ${s.new_joiners || 0}</span>` +
        `<span class="hr-badge hr-badge-rehire">Rehire/Movement: ${s.rehires_movements || 0}</span>` +
        `<span class="hr-badge hr-badge-leaver">Leavers: ${s.leavers || 0}</span>` +
        `<span class="hr-badge hr-badge-change">Field Changes: ${s.field_changes || 0} employees</span>` +
        `<span class="hr-badge">Total Affected: ${s.employees_affected || 0}</span>`;

      applyHrFilters();
      hrDiffSection.hidden = false;
      hrConfirmButton.hidden = false;
      hrSavedExclusions.hidden = true;
      updateHrExcludeHint();
    } catch (err) {
      hrReconError.textContent = err.message || String(err);
      hrReconError.hidden = false;
    } finally {
      hrCompareButton.disabled = false;
      hrCompareButton.textContent = "Compare";
    }
  });

  function applyHrFilters() {
    const showNew = hrFilterNewJoiners.checked;
    const showLeaver = hrFilterLeavers.checked;
    const showChange = hrFilterChanges.checked;

    hrVisibleChanges = hrAllChanges.filter((c) => {
      if (c.change_type === "New Joiner") return showNew;
      if (c.change_type === "Leaver") return showLeaver;
      return showChange;
    });

    renderHrDiffTable();
  }

  [hrFilterNewJoiners, hrFilterLeavers, hrFilterChanges].forEach((cb) =>
    cb.addEventListener("change", applyHrFilters)
  );

  // Exports exactly what's currently visible (respects the New Joiners /
  // Leavers / Field Changes filter checkboxes above), so what you export
  // matches what you're looking at on screen.
  function csvEscape(value) {
    const s = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  hrExportButton.addEventListener("click", function () {
    const columns = [
      ["employee_id", "Employee ID"],
      ["employee_name", "Full Name"],
      ["change_type", "Change Type"],
      ["field", "Field"],
      ["reason", "Reason"],
      ["q1_value", "Q1 Value"],
      ["q2_value", "Q2 Value"],
    ];
    const lines = [columns.map(([, label]) => csvEscape(label)).join(",")];
    hrVisibleChanges.forEach((change) => {
      lines.push(columns.map(([key]) => csvEscape(change[key])).join(","));
    });
    const csvContent = lines.join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const timestamp = new Date().toISOString().slice(0, 10);
    link.href = url;
    link.download = `hr_reconciliation_diff_${timestamp}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  });

  function renderHrDiffTable() {
    const tbody = hrDiffTable.querySelector("tbody");
    tbody.innerHTML = "";

    // Group changes by employee so each employee only has one checkbox.
    // We track the checkbox state at the employee_id level.
    hrVisibleChanges.forEach((change) => {
      const tr = document.createElement("tr");
      const isExcluded = hrExcludedIds.has(change.employee_id);

      // Checkbox cell
      const checkTd = document.createElement("td");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = isExcluded;
      cb.dataset.empId = change.employee_id;
      cb.addEventListener("change", function () {
        if (cb.checked) {
          hrExcludedIds.add(change.employee_id);
        } else {
          hrExcludedIds.delete(change.employee_id);
        }
        updateHrExcludeHint();
        syncHrExcludeAllCheckbox();
      });
      checkTd.appendChild(cb);
      tr.appendChild(checkTd);

      const changeTypeClass = {
        "New Joiner": "hr-ct-new",
        "Rehire / Movement": "hr-ct-rehire",
        "Leaver": "hr-ct-leaver",
        "Field Change": "hr-ct-change",
      }[change.change_type] || "";

      const cells = [
        change.employee_id,
        change.employee_name,
        change.change_type,
        change.field,
        change.reason,
        change.q1_value,
        change.q2_value,
      ];

      cells.forEach((val, idx) => {
        const td = document.createElement("td");
        td.textContent = val;
        if (idx === 2) td.className = changeTypeClass; // change_type column
        tr.appendChild(td);
      });

      tbody.appendChild(tr);
    });

    syncHrExcludeAllCheckbox();
    updateHrExcludeHint();
  }

  function syncHrExcludeAllCheckbox() {
    const allCbs = Array.from(hrDiffTable.querySelectorAll("tbody input[type=checkbox]"));
    if (allCbs.length === 0) {
      hrExcludeAll.checked = false;
      hrExcludeAll.indeterminate = false;
      return;
    }
    const checkedCount = allCbs.filter((c) => c.checked).length;
    hrExcludeAll.indeterminate = checkedCount > 0 && checkedCount < allCbs.length;
    hrExcludeAll.checked = checkedCount === allCbs.length;
  }

  hrExcludeAll.addEventListener("change", function () {
    const checked = hrExcludeAll.checked;
    hrDiffTable.querySelectorAll("tbody input[type=checkbox]").forEach((cb) => {
      cb.checked = checked;
      if (checked) hrExcludedIds.add(cb.dataset.empId);
      else hrExcludedIds.delete(cb.dataset.empId);
    });
    updateHrExcludeHint();
  });

  function updateHrExcludeHint() {
    const count = hrExcludedIds.size;
    hrExcludeHint.textContent = count === 0
      ? "No employees selected for exclusion — all will be included in calculations."
      : `${count} employee(s) selected for exclusion. These will be skipped in all future calculations until you update this list.`;
  }

  hrConfirmButton.addEventListener("click", async function () {
    hrReconError.hidden = true;
    hrConfirmButton.disabled = true;
    try {
      const resp = await fetch(`${HR_API_BASE}/exclusions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ excluded_employee_ids: Array.from(hrExcludedIds) }),
      });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      sessionStorage.setItem(HR_DONE_KEY, "true");
      hideAllMainSections();
      uploadSection.hidden = false;
    } catch (err) {
      hrReconError.textContent = `Failed to save exclusions: ${err.message || err}`;
      hrReconError.hidden = false;
    } finally {
      hrConfirmButton.disabled = false;
    }
  });

  hrSkipButton.addEventListener("click", async function () {
    // Clear any previously saved exclusions and go straight to file upload.
    hrReconError.hidden = true;
    hrSkipButton.disabled = true;
    try {
      const resp = await fetch(`${HR_API_BASE}/exclusions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ excluded_employee_ids: [] }),
      });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
    } catch (_err) {
      // Non-fatal: proceed to file upload even if save fails.
    } finally {
      hrSkipButton.disabled = false;
    }
    sessionStorage.setItem(HR_DONE_KEY, "true");
    hideAllMainSections();
    uploadSection.hidden = false;
  });

  // ---- Login / logout (client-side only, see SHARED_PASSWORD above) ----
  function showLoginScreen() {
    loginSection.hidden = false;
    appShell.hidden = true;
  }

  async function showAppShell() {
    loginSection.hidden = true;
    appShell.hidden = false;

    // Quarter/FY indicator is global (not per-run), so populate it as soon
    // as the app shell is shown, regardless of whether a run exists yet.
    loadCalculationPeriodBadge();

    // Restore a completed run on page load/reload, if one was saved.
    const restored = await restorePersistedRunIfAny();
    if (!restored) {
      if (sessionStorage.getItem(HR_DONE_KEY) === "true") {
        hideAllMainSections();
        uploadSection.hidden = false;
      } else {
        showHrSection();
      }
    }

    // If admin settings was open before the reload, reopen it to the same
    // tab - regardless of whether a run was restored. A page reload can
    // happen at any time (manual refresh, or the browser discarding an
    // idle/backgrounded tab to save memory and reloading it when it comes
    // back into focus), including before any run exists yet. Without this
    // check running unconditionally, that reload silently drops the user
    // back on Upload/HR instead of the admin tab they were actually on.
    if (sessionStorage.getItem(ADMIN_OPEN_KEY) === "true" &&
        sessionStorage.getItem(ADMIN_AUTH_STORAGE_KEY) === "true") {
      const savedTab = sessionStorage.getItem(ADMIN_TAB_KEY);
      await showAdminSection();
      if (savedTab) showAdminTab(savedTab);
    }
  }

  // ---- Admin Settings (dummy, demo-only - see DEFAULT_PARAMETERS above) ----
  function getCalculationParameters(role) {
    /**
     * Gather current parameter values for the given role to send to the backend.
     * This collects all parameters from the role's current state.
     */
    const params = getRoleParameters(role || "default");
    // Return only non-null/non-undefined values that differ from defaults
    // or return all values - the backend will use them as overrides
    return Object.fromEntries(
      Object.entries(params).filter(([, v]) => v !== null && v !== undefined)
    );
  }

  function renderAdminParameters(role) {
    const values = getRoleParameters(role);
    adminParameters.innerHTML = "";

    PARAMETER_GROUPS.forEach((group) => {
      const fieldset = document.createElement("fieldset");
      fieldset.className = "admin-group";

      const legend = document.createElement("legend");
      legend.textContent = group.title;
      fieldset.appendChild(legend);

      const grid = document.createElement("div");
      grid.className = "file-grid";

      group.keys.forEach((key) => {
        const field = document.createElement("label");
        field.className = "file-field";

        const span = document.createElement("span");
        span.textContent = formatParameterLabel(key);

        const options = SELECT_PARAMETER_OPTIONS[key];
        let input;

        if (options) {
          input = document.createElement("select");
          options.forEach((optionValue) => {
            const option = document.createElement("option");
            option.value = optionValue;
            option.textContent = optionValue;
            input.appendChild(option);
          });
          input.value = values[key];
          input.addEventListener("change", function () {
            // Demo only: updates in-memory state, nothing else.
            values[key] = input.value;
          });
        } else {
          input = document.createElement("input");
          input.type = "number";
          input.step = "0.0001";
          input.value = values[key];
          input.addEventListener("input", function () {
            // Demo only: updates in-memory state, nothing else.
            values[key] = parseFloat(input.value);
          });
        }

        field.appendChild(span);
        field.appendChild(input);
        grid.appendChild(field);
      });

      fieldset.appendChild(grid);
      adminParameters.appendChild(fieldset);
    });
  }

  function populateAdminRoleSelect() {
    adminRoleSelect.innerHTML = "";

    ADMIN_ROLES.forEach((role) => {
      const option = document.createElement("option");
      option.value = role.value;
      option.textContent = role.label;
      adminRoleSelect.appendChild(option);
    });
  }

  async function showAdminSection() {
    hideAllMainSections();
    adminSection.hidden = false;
    adminContentSection.hidden = false;
    sessionStorage.setItem(ADMIN_OPEN_KEY, "true");

    // Data Corrections and CAM Allocations tabs require an active run.
    adminTabCorrectionsButton.disabled = !currentRunId;
    adminTabCorrectionsButton.style.opacity = currentRunId ? "" : "0.45";
    adminTabCamButton.disabled = !currentRunId;
    adminTabCamButton.style.opacity = currentRunId ? "" : "0.45";
    adminTabHrExclusionsButton.disabled = !currentRunId;
    adminTabHrExclusionsButton.style.opacity = currentRunId ? "" : "0.45";

    // Show Apply Changes button and Back button only if there's an active run
    applyParametersButton.hidden = !currentRunId;

    // Show the default tab immediately so the section isn't blank while
    // loadCalculationParameters is in flight.
    showAdminTab(currentRunId ? "cam" : "parameters");

    await loadCalculationParameters();
    renderAdminParameters(adminRoleSelect.value || "default");
  }

  function hideAdminSection() {
    sessionStorage.removeItem(ADMIN_OPEN_KEY);
    sessionStorage.removeItem(ADMIN_TAB_KEY);
    hideAllMainSections();

    if (currentRunId) {
      resultsSection.hidden = false;
    } else {
      uploadSection.hidden = false;
    }
  }

  // ---- Admin tabs: Parameters / Precompute Exceptions / Data Corrections / CAM Allocations ----
  function showAdminTab(tab) {
    // Remember the active tab
    sessionStorage.setItem(ADMIN_TAB_KEY, tab);
    const showingExceptions = tab === "exceptions";
    const showingCorrections = tab === "corrections";
    const showingCam = tab === "cam";
    const showingHrExcl = tab === "hr-exclusions";
    const showingParameters = !showingExceptions && !showingCorrections && !showingCam && !showingHrExcl;

    // Widen the page only for the Precompute Exceptions tab (13 columns) -
    // every other admin tab and page section keeps the normal 1100px width.
    // #admin-content-section is a sibling of #admin-section (see index.html)
    // so widening it never moves the header/tab bar above it.
    adminContentSection.classList.toggle("admin-content--wide-exceptions", showingExceptions);

    adminParametersPanel.hidden = !showingParameters;
    exceptionsPanel.hidden = !showingExceptions;
    correctionsPanel.hidden = !showingCorrections;
    camPanel.hidden = !showingCam;
    hrExclusionsPanel.hidden = !showingHrExcl;

    adminTabParametersButton.classList.toggle("active", showingParameters);
    adminTabExceptionsButton.classList.toggle("active", showingExceptions);
    adminTabCorrectionsButton.classList.toggle("active", showingCorrections);
    adminTabCamButton.classList.toggle("active", showingCam);
    adminTabHrExclusionsButton.classList.toggle("active", showingHrExcl);

    if (showingExceptions) {
      parametersStatus.hidden = true;
      parametersError.hidden = true;
      exceptionsError.hidden = true;
      exceptionsStatus.hidden = true;
      exceptionsViewResultsButton.hidden = true;
      exceptionsRecalculateButton.hidden = true;
      exceptionsUploadSummary.hidden = true;
      exceptionsSearchInput.value = "";
      exceptionsSearchTerm = "";
      exceptionsColumnFilters = makeDefaultExceptionsColumnFilters();
      exceptionsPendingDeleteIds.clear();
      exceptionsPendingDeletePanel.hidden = true;
      exceptionsPendingRecalcNotes.clear();
      loadExceptionCategories();
      loadExceptions();
    } else if (showingCorrections) {
      parametersStatus.hidden = true;
      parametersError.hidden = true;
      correctionsError.hidden = true;
      correctionsStatus.hidden = true;
      correctionsDeletionPending = false;
      correctionsApplyAllButton.hidden = true;
      correctionsViewResultsButton.hidden = true;
      loadCorrectionFiles();
      loadCorrections();
    } else if (showingCam) {
      parametersStatus.hidden = true;
      parametersError.hidden = true;
      camError.hidden = true;
      camStatus.hidden = true;
      camViewResultsButton.hidden = true;
      camSearchInput.value = "";
      camSearchTerm = "";
      loadCamOverrides();
    } else if (showingHrExcl) {
      parametersStatus.hidden = true;
      parametersError.hidden = true;
      hrExclError.hidden = true;
      hrExclStatus.hidden = true;
      hrExclRecalcButton.hidden = true;
      hrExclViewResultsButton.hidden = true;
      hrExclSearchInput.value = "";
      loadHrExclusions();
    } else {
      exceptionsStatus.hidden = true;
      exceptionsError.hidden = true;
    }
  }

  exceptionsViewResultsButton.addEventListener("click", function () {
    hideAdminSection();
  });

  adminTabParametersButton.addEventListener("click", function () {
    showAdminTab("parameters");
  });

  adminTabExceptionsButton.addEventListener("click", function () {
    showAdminTab("exceptions");
  });

  adminTabCorrectionsButton.addEventListener("click", function () {
    if (adminTabCorrectionsButton.disabled) return;
    showAdminTab("corrections");
  });

  adminTabCamButton.addEventListener("click", function () {
    if (adminTabCamButton.disabled) return;
    showAdminTab("cam");
  });

  // ---- Precompute Exceptions: real backend, see
  // src/sip_automation/core/precompute_exceptions.py. ----
  function currentUsername() {
    return sessionStorage.getItem(USERNAME_STORAGE_KEY) || "admin";
  }

  async function loadExceptionCategories() {
    try {
      const response = await fetch(`${EXCEPTIONS_API_BASE}/categories`, { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      if (Array.isArray(data.categories) && data.categories.length) {
        exceptionCategories = data.categories;
      }
    } catch (_err) {
      // Fall back to FALLBACK_EXCEPTION_CATEGORIES, already set.
    }
  }

  function populateExceptionCategorySelect(selectedCategory) {
    exceptionCategorySelect.innerHTML = "";

    exceptionCategories.forEach((category) => {
      const option = document.createElement("option");
      option.value = category;
      option.textContent = category;
      exceptionCategorySelect.appendChild(option);
    });

    const customOption = document.createElement("option");
    customOption.value = CUSTOM_CATEGORY_VALUE;
    customOption.textContent = "Other (type custom)";
    exceptionCategorySelect.appendChild(customOption);

    const isKnownCategory = selectedCategory && exceptionCategories.includes(selectedCategory);

    if (selectedCategory && !isKnownCategory) {
      exceptionCategorySelect.value = CUSTOM_CATEGORY_VALUE;
      exceptionCategoryCustomField.hidden = false;
      exceptionCategoryCustomInput.value = selectedCategory;
    } else {
      exceptionCategorySelect.value = selectedCategory || exceptionCategories[0] || CUSTOM_CATEGORY_VALUE;
      exceptionCategoryCustomField.hidden = true;
      exceptionCategoryCustomInput.value = "";
    }
  }

  exceptionCategorySelect.addEventListener("change", function () {
    exceptionCategoryCustomField.hidden = exceptionCategorySelect.value !== CUSTOM_CATEGORY_VALUE;
  });

  async function loadExceptions() {
    exceptionsError.hidden = true;

    try {
      // no-store: this list must always reflect the latest edit/delete, and
      // GET requests can otherwise be served from the browser's HTTP cache,
      // making a just-cleared/removed field appear unchanged until a full
      // page reload.
      const response = await fetch(EXCEPTIONS_API_BASE, { cache: "no-store" });

      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }

      const data = await response.json();
      currentExceptions = data.exceptions || [];
      populateExceptionsColumnFilters();
      renderExceptionsTable();
    } catch (err) {
      exceptionsError.textContent = err.message || String(err);
      exceptionsError.hidden = false;
    }
  }

  // Combines an amount field's amount/percentage/direction into one
  // readable table cell, e.g. "20000 (25% +)" or "20000 (-)" when no
  // percentage was entered.
  function formatExceptionAmountCell(exception, fieldKey) {
    const amount = exception[fieldKey];

    if (amount === null || amount === undefined) return "";

    const percentage = exception[`${fieldKey}_percentage`];
    const direction = exception[`${fieldKey}_direction`] || "";

    const detail =
      percentage !== null && percentage !== undefined ? `${percentage}% ${direction}` : direction;

    return detail ? `${amount} (${detail})` : String(amount);
  }

  // A complete override has no percentage/direction: just show the value.
  function formatExceptionOverrideCell(exception, fieldKey) {
    const value = exception[fieldKey];
    return value === null || value === undefined ? "" : String(value);
  }

  // "exact" columns get a dropdown of the distinct values present in the
  // data (rebuilt on every load) - good for columns with a small, discrete
  // set of values. "has" columns get a static Has data/Empty toggle instead,
  // since these are continuous amount fields where a distinct-value dropdown
  // would be unusably long - what's actually useful is finding which rows
  // have that field populated at all.
  const EXCEPTIONS_COLUMN_FILTER_FIELDS = [
    { key: "employee_id", select: () => exceptionsFilterEmployeeId, type: "exact" },
    { key: "employee_name", select: () => exceptionsFilterEmployeeName, type: "exact" },
    { key: "category", select: () => exceptionsFilterCategory, type: "exact" },
    { key: "months_eligible_override", select: () => exceptionsFilterMonthsEligible, type: "has" },
    { key: "bp_fy26_rev", select: () => exceptionsFilterBpRev, type: "has" },
    { key: "bp_fy26_gp", select: () => exceptionsFilterBpGp, type: "has" },
    { key: "ytd_fy26_rev", select: () => exceptionsFilterYtdRev, type: "has" },
    { key: "ytd_fy26_gp", select: () => exceptionsFilterYtdGp, type: "has" },
    { key: "ytd_actual_revenue_override", select: () => exceptionsFilterYtdActualRevenue, type: "has" },
    { key: "ytd_actual_gp_dop_override", select: () => exceptionsFilterYtdActualGpDop, type: "has" },
    { key: "bp_sga", select: () => exceptionsFilterBpSga, type: "has" },
    { key: "ytd_sga", select: () => exceptionsFilterYtdSga, type: "has" },
  ];

  // Rebuilds each "exact" column filter dropdown with the distinct values
  // present in the currently loaded exceptions, preserving the current
  // selection when it's still one of the available options. "has" columns
  // use a fixed set of options defined in the HTML, so they don't need
  // rebuilding here.
  function populateExceptionsColumnFilters() {
    EXCEPTIONS_COLUMN_FILTER_FIELDS.filter((f) => f.type === "exact").forEach(({ key, select }) => {
      const el = select();
      const values = Array.from(
        new Set(currentExceptions.map((e) => e[key]).filter((v) => v !== null && v !== undefined && v !== ""))
      ).sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));

      const previousValue = exceptionsColumnFilters[key];
      el.innerHTML = "";

      const allOption = document.createElement("option");
      allOption.value = "";
      allOption.textContent = "All";
      el.appendChild(allOption);

      values.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        el.appendChild(option);
      });

      const stillValid = previousValue && values.includes(previousValue);
      exceptionsColumnFilters[key] = stillValid ? previousValue : "";
      el.value = exceptionsColumnFilters[key];
    });
  }

  function renderExceptionsTable() {
    const tbody = exceptionsTable.querySelector("tbody");
    tbody.innerHTML = "";

    const rowsWithCells = currentExceptions.map((exception) => ({
      exception,
      cells: [
        exception.employee_id,
        exception.employee_name || "",
        exception.category || "",
        formatExceptionAmountCell(exception, "bp_fy26_rev"),
        formatExceptionAmountCell(exception, "bp_fy26_gp"),
        formatExceptionAmountCell(exception, "ytd_fy26_rev"),
        formatExceptionAmountCell(exception, "ytd_fy26_gp"),
        formatExceptionOverrideCell(exception, "months_eligible_override"),
        formatExceptionOverrideCell(exception, "ytd_actual_revenue_override"),
        formatExceptionOverrideCell(exception, "ytd_actual_gp_dop_override"),
        formatExceptionOverrideCell(exception, "bp_sga"),
        formatExceptionOverrideCell(exception, "ytd_sga"),
      ],
    }));

    const visibleRows = rowsWithCells.filter(({ exception, cells }) => {
      if (exceptionsPendingDeleteIds.has(exception.id)) return false;

      const matchesColumnFilters = EXCEPTIONS_COLUMN_FILTER_FIELDS.every(({ key, type }) => {
        const selected = exceptionsColumnFilters[key];
        if (!selected) return true;
        const rawValue = exception[key];
        const hasValue = rawValue !== null && rawValue !== undefined && rawValue !== "";

        if (type === "has") {
          return selected === "has" ? hasValue : !hasValue;
        }

        const asString = hasValue ? String(rawValue) : "";
        return asString === selected;
      });
      if (!matchesColumnFilters) return false;

      if (!exceptionsSearchTerm) return true;
      return cells.some((value) => String(value || "").toLowerCase().includes(exceptionsSearchTerm));
    });

    if (visibleRows.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 13;
      td.textContent = exceptionsSearchTerm || Object.values(exceptionsColumnFilters).some(Boolean)
        ? "No exceptions match your search."
        : "No exceptions have been added yet.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    visibleRows.forEach(({ exception, cells }) => {
      const tr = document.createElement("tr");

      cells.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });

      const actionTd = document.createElement("td");

      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.className = "btn btn-edit";
      editButton.textContent = "Edit";
      editButton.addEventListener("click", () => openExceptionModal(exception));

      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "btn btn-delete";
      deleteButton.textContent = "Delete";
      deleteButton.style.marginLeft = "8px";
      deleteButton.addEventListener("click", () => deleteException(exception));

      actionTd.appendChild(editButton);
      actionTd.appendChild(deleteButton);
      tr.appendChild(actionTd);

      tbody.appendChild(tr);
    });
  }

  function openExceptionModal(exception) {
    exceptionFormError.hidden = true;
    exceptionForm.reset();

    editingExceptionId = exception ? exception.id : null;
    exceptionModalTitle.textContent = exception ? "Edit Exception" : "Add Exception";

    exceptionEmployeeIdInput.value = exception ? exception.employee_id : "";
    exceptionEmployeeNameInput.value = (exception && exception.employee_name) || "";
    populateExceptionCategorySelect(exception ? exception.category : "");

    EXCEPTION_AMOUNT_FIELDS.forEach(({ key, amountInput, percentageInput, directionSelect }) => {
      const amount = exception ? exception[key] : null;
      const percentage = exception ? exception[`${key}_percentage`] : null;
      const direction = exception ? exception[`${key}_direction`] : null;

      amountInput.value = amount !== null && amount !== undefined ? amount : "";
      percentageInput.value = percentage !== null && percentage !== undefined ? percentage : "";
      directionSelect.value = direction || "+";
    });

    EXCEPTION_OVERRIDE_FIELDS.forEach(({ key, valueInput }) => {
      const value = exception ? exception[key] : null;
      valueInput.value = value !== null && value !== undefined ? value : "";
    });

    EXCEPTION_SGA_FIELDS.forEach(({ key, valueInput }) => {
      const value = exception ? exception[key] : null;
      valueInput.value = value !== null && value !== undefined ? value : "";
    });

    exceptionModal.hidden = false;
  }

  function closeExceptionModal() {
    exceptionModal.hidden = true;
    editingExceptionId = null;
  }

  exceptionsAddButton.addEventListener("click", function () {
    openExceptionModal(null);
  });

  exceptionsSearchInput.addEventListener("input", function () {
    exceptionsSearchTerm = exceptionsSearchInput.value.trim().toLowerCase();
    renderExceptionsTable();
  });

  EXCEPTIONS_COLUMN_FILTER_FIELDS.forEach(({ key, select }) => {
    select().addEventListener("change", function () {
      exceptionsColumnFilters[key] = select().value;
      renderExceptionsTable();
    });
  });

  exceptionsClearFiltersButton.addEventListener("click", function () {
    exceptionsSearchInput.value = "";
    exceptionsSearchTerm = "";
    exceptionsColumnFilters = makeDefaultExceptionsColumnFilters();
    EXCEPTIONS_COLUMN_FILTER_FIELDS.forEach(({ select }) => {
      select().value = "";
    });
    renderExceptionsTable();
  });

  exceptionModalCloseButton.addEventListener("click", closeExceptionModal);
  exceptionFormCancelButton.addEventListener("click", closeExceptionModal);

  exceptionModal.addEventListener("click", function (event) {
    if (event.target === exceptionModal) closeExceptionModal();
  });

  function parseOptionalNumber(inputElement) {
    const raw = inputElement.value.trim();
    return raw === "" ? null : Number(raw);
  }

  // Pressing Enter while typing in any amount/percentage field (or hitting
  // Tab/Enter out of habit) would otherwise implicitly submit the form via
  // the browser's default behavior, saving the exception before all 4
  // groups are filled in and immediately closing the modal - this is very
  // likely why the panel appeared to "disappear" mid-edit. Only an explicit
  // click on the Save button (or Enter while that button itself has focus)
  // should submit.
  exceptionForm.addEventListener("keydown", function (event) {
    if (event.key !== "Enter") return;
    if (event.target && event.target.tagName === "BUTTON") return;
    event.preventDefault();
  });

  exceptionForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    exceptionFormError.hidden = true;

    const clickedApply = Boolean(
      event.submitter && event.submitter.id === "exception-form-apply-button"
    );

    const categorySelection = exceptionCategorySelect.value;
    const category =
      categorySelection === CUSTOM_CATEGORY_VALUE
        ? exceptionCategoryCustomInput.value.trim() || null
        : categorySelection || null;

    const payload = {
      employee_id: exceptionEmployeeIdInput.value.trim(),
      employee_name: exceptionEmployeeNameInput.value.trim() || null,
      category: category,
      changed_by: currentUsername(),
    };

    let validationError = null;

    EXCEPTION_AMOUNT_FIELDS.forEach(({ key, amountInput, percentageInput, directionSelect }) => {
      if (validationError) return;

      const amount = parseOptionalNumber(amountInput);
      const percentageRaw = percentageInput.value.trim();
      const percentage = percentageRaw === "" ? null : Number(percentageRaw);
      const direction = directionSelect.value || null;

      if (percentage !== null && percentage < 0) {
        validationError = `${key.replace(/_/g, " ")}: percentage cannot be negative.`;
        return;
      }

      if (amount !== null && !direction) {
        validationError = `${key.replace(/_/g, " ")}: direction (+ or -) is required when an amount is entered.`;
        return;
      }

      payload[key] = amount;
      payload[`${key}_percentage`] = percentage;
      payload[`${key}_direction`] = amount !== null ? direction : null;
    });

    EXCEPTION_OVERRIDE_FIELDS.forEach(({ key, valueInput }) => {
      payload[key] = parseOptionalNumber(valueInput);
    });

    EXCEPTION_SGA_FIELDS.forEach(({ key, valueInput }) => {
      payload[key] = parseOptionalNumber(valueInput);
    });

    if (!payload.employee_id) {
      exceptionFormError.textContent = "Employee ID is required.";
      exceptionFormError.hidden = false;
      return;
    }

    if (validationError) {
      exceptionFormError.textContent = validationError;
      exceptionFormError.hidden = false;
      return;
    }

    try {
      const url = editingExceptionId ? `${EXCEPTIONS_API_BASE}/${editingExceptionId}` : EXCEPTIONS_API_BASE;
      const method = editingExceptionId ? "PUT" : "POST";

      const response = await fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }

      closeExceptionModal();
      await loadExceptions();

      if (clickedApply) {
        await recalculateAndShowResults(true);
        return;
      }

      // "Save" only persists the exception - it must NOT recalculate or
      // change results. Only "Apply" (or "Recalculate Now") should do that.
      if (currentRunId) {
        exceptionsPendingRecalcNotes.add(payload.employee_id);
        showPendingRecalcBanner();
      }
    } catch (err) {
      exceptionFormError.textContent = err.message || String(err);
      exceptionFormError.hidden = false;
    }
  });

  // Renders the accumulated list of changes (Save/Upload) made since the
  // last successful recalculate, so it's still clear what's pending even
  // after editing several exceptions in a row instead of just the most
  // recent one.
  function showPendingRecalcBanner() {
    const notes = Array.from(exceptionsPendingRecalcNotes);
    const summary = notes.length > 1
      ? `${notes.length} changes since last recalculate (${notes.join(", ")})`
      : notes[0] || "Saved";
    exceptionsStatus.textContent =
      `${summary}. Results are not updated yet - click "Recalculate Now" to apply.`;
    exceptionsStatus.hidden = false;
    exceptionsRecalculateButton.hidden = false;
  }

  async function recalculateAndShowResults(navigateToResults) {
    if (!currentRunId) {
      exceptionsStatus.textContent =
        "No active run yet - this will apply automatically the next time you run the pipeline.";
      exceptionsStatus.hidden = false;
      return;
    }

    exceptionsStatus.textContent = "Recalculating SIP results with the updated exceptions...";
    exceptionsStatus.hidden = false;

    try {
      const calculationParams = getCalculationParameters("default");
      const response = await fetch(`${API_BASE}/${currentRunId}/calculations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(calculationParams),
      });

      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }

      const calculationsResult = await response.json();
      populateRoleSelect(calculationsResult.enabled_roles, calculationsResult.role_row_counts);
      await loadResults(roleSelect.value);
      persistRun(currentRunId, calculationsResult.enabled_roles, calculationsResult.role_row_counts);

      // Recalculation succeeded, so every change tracked in the pending
      // banner is now reflected in results - clear it before either branch
      // below decides what (if anything) to show next.
      exceptionsPendingRecalcNotes.clear();

      if (navigateToResults) {
        // "Apply" was clicked - jump straight to Results with the freshly
        // recalculated data already loaded, no manual click/reload needed.
        exceptionsStatus.hidden = true;
        hideAdminSection();
        return;
      }

      // "Save" was clicked - stay on the Precompute Exceptions panel so the
      // updated exception list is visible. Results are already recalculated
      // in the background and ready to view on demand.
      exceptionsStatus.textContent =
        "Recalculated. Results are up to date - click \"View Results\" to see them.";
      exceptionsStatus.hidden = false;
      exceptionsViewResultsButton.hidden = false;
    } catch (err) {
      exceptionsStatus.hidden = true;
      exceptionsError.textContent = `Recalculation failed: ${err.message || err}`;
      exceptionsError.hidden = false;
    }
  }

  async function deleteException(exception) {
    const confirmed = window.confirm(
      `Stage the exception for employee ${exception.employee_id} for deletion? ` +
        `It won't actually be removed (and results won't be recalculated) until ` +
        `you click "Apply Deletions".`
    );
    if (!confirmed) return;

    exceptionsPendingDeleteIds.add(exception.id);
    renderExceptionsTable();
    renderPendingDeletions();
  }

  // Renders the staged-for-deletion list below the exceptions table and
  // wires up each row's Undo button. Deleting several employees now stages
  // them all here first - nothing is actually removed, and no recalculation
  // happens, until "Apply Deletions" is clicked once for the whole batch.
  function renderPendingDeletions() {
    exceptionsPendingDeleteList.innerHTML = "";

    const pendingExceptions = currentExceptions.filter((exception) =>
      exceptionsPendingDeleteIds.has(exception.id)
    );

    exceptionsPendingDeletePanel.hidden = pendingExceptions.length === 0;
    exceptionsPendingDeleteCount.textContent = String(pendingExceptions.length);

    pendingExceptions.forEach((exception) => {
      const li = document.createElement("li");

      const label = document.createElement("span");
      label.textContent = `${exception.employee_id}${exception.employee_name ? " - " + exception.employee_name : ""}`;
      li.appendChild(label);

      const undoButton = document.createElement("button");
      undoButton.type = "button";
      undoButton.className = "btn btn-secondary";
      undoButton.textContent = "Undo";
      undoButton.addEventListener("click", () => {
        exceptionsPendingDeleteIds.delete(exception.id);
        renderExceptionsTable();
        renderPendingDeletions();
      });
      li.appendChild(undoButton);

      exceptionsPendingDeleteList.appendChild(li);
    });
  }

  exceptionsApplyDeletionsButton.addEventListener("click", async function () {
    const idsToDelete = Array.from(exceptionsPendingDeleteIds);
    if (idsToDelete.length === 0) return;

    const confirmed = window.confirm(
      `Delete ${idsToDelete.length} staged exception(s)? This cannot be undone.`
    );
    if (!confirmed) return;

    exceptionsError.hidden = true;
    exceptionsApplyDeletionsButton.disabled = true;
    exceptionsCancelDeletionsButton.disabled = true;

    try {
      for (const id of idsToDelete) {
        const response = await fetch(
          `${EXCEPTIONS_API_BASE}/${id}?changed_by=${encodeURIComponent(currentUsername())}`,
          { method: "DELETE" }
        );

        if (!response.ok && response.status !== 204) {
          throw new Error(await readErrorDetail(response));
        }
      }

      exceptionsPendingDeleteIds.clear();
      await loadExceptions();
      await recalculateAndShowResults(false);
      renderPendingDeletions();
    } catch (err) {
      exceptionsError.textContent = err.message || String(err);
      exceptionsError.hidden = false;
    } finally {
      exceptionsApplyDeletionsButton.disabled = false;
      exceptionsCancelDeletionsButton.disabled = false;
    }
  });

  exceptionsCancelDeletionsButton.addEventListener("click", function () {
    exceptionsPendingDeleteIds.clear();
    renderExceptionsTable();
    renderPendingDeletions();
  });

  // ---- Precompute Exceptions: bulk upload (replaces the entire list) ----

  exceptionsUploadButton.addEventListener("click", function () {
    exceptionsUploadInput.click();
  });

  exceptionsUploadInput.addEventListener("change", async function () {
    const file = exceptionsUploadInput.files && exceptionsUploadInput.files[0];
    if (!file) return;

    const confirmed = window.confirm(
      "Uploading will add or update the employees in this file. If an " +
        "employee in the file already has an exception, the file's values " +
        "will replace it. Other existing exceptions are kept. Continue?"
    );
    if (!confirmed) {
      exceptionsUploadInput.value = "";
      return;
    }

    exceptionsError.hidden = true;
    exceptionsUploadSummary.hidden = true;
    exceptionsRecalculateButton.hidden = true;
    exceptionsStatus.textContent = "Uploading exceptions...";
    exceptionsStatus.hidden = false;

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(
        `${EXCEPTIONS_API_BASE}/upload?changed_by=${encodeURIComponent(currentUsername())}`,
        { method: "POST", body: formData }
      );

      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }

      const result = await response.json();
      renderExceptionUploadSummary(result);

      // Uploading merges by employee_id (see merge_from_upload) - IDs
      // present in this upload get new row ids, so any staged deletions
      // may no longer refer to real rows. Simplest to just drop them; the
      // fresh loadExceptions() below re-renders the current state anyway.
      exceptionsPendingDeleteIds.clear();
      await loadExceptions();
      renderPendingDeletions();
      if (result.saved_count > 0) {
        exceptionsPendingRecalcNotes.add(
          `${result.saved_count} employee(s) via upload`
        );
        showPendingRecalcBanner();
      } else {
        exceptionsStatus.hidden = true;
        exceptionsRecalculateButton.hidden = false;
      }
    } catch (err) {
      exceptionsStatus.hidden = true;
      exceptionsError.textContent = `Upload failed: ${err.message || err}`;
      exceptionsError.hidden = false;
    } finally {
      exceptionsUploadInput.value = "";
    }
  });

  function renderExceptionUploadSummary(result) {
    const lines = [
      `Uploaded ${result.total_rows} row(s): ${result.saved_count} saved, ${result.error_count} failed.`,
    ];

    if (result.errors && result.errors.length > 0) {
      result.errors.forEach((rowError) => {
        const who = rowError.employee_id ? ` (employee ${rowError.employee_id})` : "";
        lines.push(`Row ${rowError.row_number}${who}: ${rowError.error}`);
      });
    }

    exceptionsUploadSummary.innerHTML = lines
      .map((line, index) => (index === 0 ? `<strong>${line}</strong>` : line))
      .join("<br>");
    exceptionsUploadSummary.hidden = false;
  }

  exceptionsRecalculateButton.addEventListener("click", async function () {
    exceptionsRecalculateButton.hidden = true;
    await recalculateAndShowResults(true);
  });

  adminTabHrExclusionsButton.addEventListener("click", function () {
    if (adminTabHrExclusionsButton.disabled) return;
    showAdminTab("hr-exclusions");
  });

  // ---- HR Exclusions (admin tab) ----

  async function loadHrExclusions() {
    hrExclError.hidden = true;
    try {
      const resp = await fetch(`${HR_API_BASE}/exclusions`, { cache: "no-store" });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      const data = await resp.json();
      hrExclusions = data.excluded_employee_ids || [];
      hrExclusionsDirty = false;
      renderHrExclusions();
    } catch (err) {
      hrExclError.textContent = err.message || String(err);
      hrExclError.hidden = false;
    }
  }

  function renderHrExclusions() {
    const term = hrExclSearchInput.value.trim().toLowerCase();
    const visible = term ? hrExclusions.filter((id) => id.toLowerCase().includes(term)) : hrExclusions;

    hrExclList.innerHTML = "";

    if (visible.length > 0) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.style.cssText = "width:100%;margin:0 0 8px;";
      hint.textContent = "Click \u2018Include Back\u2019 on any employee to remove them from the exclusion list, then click Recalculate.";
      hrExclList.appendChild(hint);
    }

    visible.forEach((empId) => {
      const chip = document.createElement("span");
      chip.className = "hr-exclusion-chip";

      const label = document.createElement("span");
      label.textContent = empId;
      chip.appendChild(label);

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.textContent = "Include Back";
      removeBtn.title = "Remove this employee from exclusions so they are included in calculations";
      removeBtn.style.cssText = "margin-left:10px;padding:2px 8px;font-size:11px;border-radius:10px;border:1px solid #888;background:#fff;color:#333;cursor:pointer;white-space:nowrap;";
      removeBtn.addEventListener("mouseenter", function () { removeBtn.style.background = "#e6f4ea"; removeBtn.style.borderColor = "#2e7d32"; removeBtn.style.color = "#2e7d32"; });
      removeBtn.addEventListener("mouseleave", function () { removeBtn.style.background = "#fff"; removeBtn.style.borderColor = "#888"; removeBtn.style.color = "#333"; });
      removeBtn.addEventListener("click", async function () {
        removeBtn.textContent = "Saving…";
        removeBtn.disabled = true;
        removeBtn.style.opacity = "0.6";
        hrExclusions = hrExclusions.filter((id) => id !== empId);
        await saveHrExclusions();
        hrExclusionsDirty = true;
        renderHrExclusions();
        hrExclStatus.textContent = `${empId} removed from exclusions. Click Recalculate to update results.`;
        hrExclStatus.hidden = false;
        hrExclViewResultsButton.hidden = true;
      });
      chip.appendChild(removeBtn);
      hrExclList.appendChild(chip);
    });

    hrExclEmpty.hidden = hrExclusions.length > 0;
    hrExclRecalcButton.hidden = !(currentRunId && hrExclusionsDirty);
  }

  async function saveHrExclusions() {
    await fetch(`${HR_API_BASE}/exclusions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ excluded_employee_ids: hrExclusions }),
    });
  }

  hrExclAddButton.addEventListener("click", async function () {
    const empId = window.prompt("Enter Employee ID to exclude:");
    if (!empId || !empId.trim()) return;
    const id = empId.trim();
    if (hrExclusions.includes(id)) {
      alert(`${id} is already in the exclusion list.`);
      return;
    }
    hrExclusions.push(id);
    await saveHrExclusions();
    hrExclusionsDirty = true;
    renderHrExclusions();
  });

  hrExclSearchInput.addEventListener("input", function () {
    renderHrExclusions();
  });

  hrExclRecalcButton.addEventListener("click", async function () {
    if (!currentRunId) return;
    hrExclError.hidden = true;
    hrExclStatus.textContent = "⏳ Running SIP calculations with updated exclusions… this may take a moment.";
    hrExclStatus.hidden = false;
    hrExclRecalcButton.disabled = true;
    hrExclRecalcButton.textContent = "Calculating…";
    hrExclAddButton.disabled = true;

    try {
      const calculationParams = getCalculationParameters("default");
      const resp = await fetch(`${API_BASE}/${currentRunId}/calculations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(calculationParams),
      });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      const result = await resp.json();
      populateRoleSelect(result.enabled_roles, result.role_row_counts);
      await loadResults(roleSelect.value);
      persistRun(currentRunId, result.enabled_roles, result.role_row_counts);

      hrExclStatus.textContent = "✓ Done. Results updated with the new exclusion list.";
      hrExclViewResultsButton.hidden = false;
      hrExclusionsDirty = false;
      renderHrExclusions();
    } catch (err) {
      hrExclStatus.hidden = true;
      hrExclError.textContent = `Recalculation failed: ${err.message || err}`;
      hrExclError.hidden = false;
    } finally {
      hrExclRecalcButton.disabled = false;
      hrExclRecalcButton.textContent = "Recalculate";
      hrExclAddButton.disabled = false;
    }
  });

  hrExclViewResultsButton.addEventListener("click", function () {
    hideAdminSection();
  });

  // ---- Data Corrections ----

  async function loadCorrectionFiles() {
    if (Object.keys(correctionFileOptions).length > 0) return; // already loaded
    try {
      const resp = await fetch(`${CORRECTIONS_API_BASE}/files`, { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        correctionFileOptions = data.files || {};
      }
    } catch (_err) {
      // keep empty — form will show a plain text input fallback handled below
    }
  }

  async function loadCorrections() {
    correctionsError.hidden = true;
    try {
      const resp = await fetch(CORRECTIONS_API_BASE, { cache: "no-store" });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      const data = await resp.json();
      currentCorrections = data.corrections || [];
      renderCorrectionsTable();
      updateCorrectionsApplyButtonVisibility();
    } catch (err) {
      correctionsError.textContent = err.message || String(err);
      correctionsError.hidden = false;
    }
  }

  // "Apply All Changes" must stay visible whenever there are corrections
  // that haven't been (re)applied to the current run - not just right after
  // an add/edit/delete in this same page load. Otherwise switching tabs or
  // reloading the page makes the button disappear even though the
  // corrections on file still haven't been applied yet. Also stays visible
  // when a deletion is pending a rebuild, even if that emptied the list.
  function updateCorrectionsApplyButtonVisibility() {
    correctionsApplyAllButton.hidden = !(
      currentRunId &&
      (currentCorrections.length > 0 || correctionsDeletionPending)
    );
  }

  function renderCorrectionsTable() {
    const tbody = correctionsTable.querySelector("tbody");
    tbody.innerHTML = "";
    currentCorrections.forEach((correction) => {
      const tr = document.createElement("tr");
      const fileLabel = correctionFileOptions[correction.source_file] || correction.source_file;
      [
        correction.employee_id,
        correction.employee_name || "",
        fileLabel,
        correction.column_name,
        correction.new_value,
        correction.note || "",
      ].forEach((val) => {
        const td = document.createElement("td");
        td.textContent = val;
        tr.appendChild(td);
      });
      const actionTd = document.createElement("td");
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn btn-edit";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", () => openCorrectionModal(correction));
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn btn-delete";
      delBtn.textContent = "Delete";
      delBtn.style.marginLeft = "8px";
      delBtn.addEventListener("click", () => deleteCorrection(correction));
      actionTd.appendChild(editBtn);
      actionTd.appendChild(delBtn);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
  }

  async function loadColumnsForFile(sourceFile, selectedColumn) {
    try {
      const resp = await fetch(`${CORRECTIONS_API_BASE}/columns/${encodeURIComponent(sourceFile)}`, { cache: "no-store" });
      const data = resp.ok ? await resp.json() : { columns: [] };
      const columns = data.columns || [];

      if (columns.length > 0) {
        correctionColumnNameSelect.innerHTML = "";
        columns.forEach((col) => {
          const opt = document.createElement("option");
          opt.value = col;
          opt.textContent = col;
          correctionColumnNameSelect.appendChild(opt);
        });
        if (selectedColumn) correctionColumnNameSelect.value = selectedColumn;
        correctionColumnNameSelect.hidden = false;
        correctionColumnNameInput.hidden = true;
        correctionColumnNameInput.removeAttribute("required");
      } else {
        // No run yet — fall back to free text
        correctionColumnNameSelect.hidden = true;
        correctionColumnNameInput.hidden = false;
        correctionColumnNameInput.setAttribute("required", "");
        if (selectedColumn) correctionColumnNameInput.value = selectedColumn;
      }
    } catch (_err) {
      correctionColumnNameSelect.hidden = true;
      correctionColumnNameInput.hidden = false;
      correctionColumnNameInput.setAttribute("required", "");
    }
  }

  correctionSourceFileSelect.addEventListener("change", function () {
    loadColumnsForFile(correctionSourceFileSelect.value, null);
  });

  function populateCorrectionFileSelect(selectedFile) {
    correctionSourceFileSelect.innerHTML = "";
    Object.entries(correctionFileOptions).forEach(([key, label]) => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = label;
      correctionSourceFileSelect.appendChild(opt);
    });
    if (selectedFile) correctionSourceFileSelect.value = selectedFile;
  }

  async function openCorrectionModal(correction) {
    correctionFormError.hidden = true;
    correctionForm.reset();
    editingCorrectionId = correction ? correction.id : null;
    correctionModalTitle.textContent = correction ? "Edit Correction" : "Add Correction";
    correctionEmployeeIdInput.value = correction ? correction.employee_id : "";
    correctionEmployeeNameInput.value = (correction && correction.employee_name) || "";
    populateCorrectionFileSelect(correction ? correction.source_file : null);
    const colVal = (correction && correction.column_name) || "";
    await loadColumnsForFile(
      correctionSourceFileSelect.value || Object.keys(correctionFileOptions)[0] || "employee",
      colVal
    );
    correctionNewValueInput.value = (correction && correction.new_value) || "";
    correctionNoteInput.value = (correction && correction.note) || "";
    correctionModal.hidden = false;
  }

  function closeCorrectionModal() {
    correctionModal.hidden = true;
    editingCorrectionId = null;
  }

  correctionModalClose.addEventListener("click", closeCorrectionModal);
  correctionFormCancel.addEventListener("click", closeCorrectionModal);
  correctionModal.addEventListener("click", function (e) {
    if (e.target === correctionModal) closeCorrectionModal();
  });

  correctionForm.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target && e.target.tagName !== "BUTTON") e.preventDefault();
  });

  correctionsAddButton.addEventListener("click", async function () {
    openCorrectionModal(null);
  });

  correctionForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    correctionFormError.hidden = true;

    const column_name = correctionColumnNameSelect.hidden
      ? correctionColumnNameInput.value.trim()
      : correctionColumnNameSelect.value;

    const payload = {
      employee_id: correctionEmployeeIdInput.value.trim(),
      employee_name: correctionEmployeeNameInput.value.trim() || null,
      source_file: correctionSourceFileSelect.value,
      column_name: column_name,
      new_value: correctionNewValueInput.value.trim(),
      note: correctionNoteInput.value.trim() || null,
      changed_by: currentUsername(),
    };

    if (!payload.employee_id) {
      correctionFormError.textContent = "Employee ID is required.";
      correctionFormError.hidden = false;
      return;
    }
    if (!payload.column_name) {
      correctionFormError.textContent = "Column Name is required.";
      correctionFormError.hidden = false;
      return;
    }
    if (!payload.new_value) {
      correctionFormError.textContent = "New Value is required.";
      correctionFormError.hidden = false;
      return;
    }

    try {
      const url = editingCorrectionId
        ? `${CORRECTIONS_API_BASE}/${editingCorrectionId}`
        : CORRECTIONS_API_BASE;
      const method = editingCorrectionId ? "PUT" : "POST";
      const resp = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      closeCorrectionModal();
      await loadCorrections();
      const savedVerb = editingCorrectionId ? "Correction updated." : "Correction saved.";
      if (currentRunId) {
        correctionsStatus.textContent = `${savedVerb} Click "Apply All Changes" to rebuild canonical data and recalculate.`;
        correctionsStatus.hidden = false;
      } else {
        correctionsStatus.textContent = `${savedVerb} It will apply the next time you run the pipeline.`;
        correctionsStatus.hidden = false;
      }
    } catch (err) {
      correctionFormError.textContent = err.message || String(err);
      correctionFormError.hidden = false;
    }
  });

  async function deleteCorrection(correction) {
    const confirmed = window.confirm(
      `Delete the correction for employee ${correction.employee_id} (${correction.column_name})? This cannot be undone.`
    );
    if (!confirmed) return;
    correctionsError.hidden = true;
    try {
      const resp = await fetch(
        `${CORRECTIONS_API_BASE}/${correction.id}?changed_by=${encodeURIComponent(currentUsername())}`,
        { method: "DELETE" }
      );
      if (!resp.ok && resp.status !== 204) throw new Error(await readErrorDetail(resp));
      correctionsDeletionPending = true;
      await loadCorrections();
      if (currentRunId) {
        correctionsStatus.textContent = "Correction deleted. Click \"Apply All Changes\" to rebuild canonical data and recalculate.";
        correctionsStatus.hidden = false;
      } else {
        correctionsStatus.textContent = "Correction deleted. It will apply the next time you run the pipeline.";
        correctionsStatus.hidden = false;
      }
    } catch (err) {
      correctionsError.textContent = err.message || String(err);
      correctionsError.hidden = false;
    }
  }

  correctionsApplyAllButton.addEventListener("click", async function () {
    if (!currentRunId) return;
    correctionsError.hidden = true;
    correctionsStatus.textContent = "Rebuilding canonical data with corrections…";
    correctionsStatus.hidden = false;
    correctionsApplyAllButton.disabled = true;

    try {
      // Data corrections apply at canonical stage, so re-run both canonical + calculations
      const canonResp = await fetch(`${API_BASE}/${currentRunId}/canonical`, { method: "POST" });
      if (!canonResp.ok) throw new Error(await readErrorDetail(canonResp));

      correctionsStatus.textContent = "Running SIP calculations…";
      const calcParams = getCalculationParameters("default");
      const calcResp = await fetch(`${API_BASE}/${currentRunId}/calculations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(calcParams),
      });
      if (!calcResp.ok) throw new Error(await readErrorDetail(calcResp));

      const result = await calcResp.json();
      populateRoleSelect(result.enabled_roles, result.role_row_counts);
      await loadResults(roleSelect.value);
      persistRun(currentRunId, result.enabled_roles, result.role_row_counts);

      correctionsStatus.hidden = true;
      correctionsApplyAllButton.hidden = true;
      correctionsViewResultsButton.hidden = false;
      correctionsStatus.textContent = "Done. Click \"View Results\" to see updated results.";
      correctionsStatus.hidden = false;
    } catch (err) {
      correctionsStatus.hidden = true;
      correctionsError.textContent = `Apply failed: ${err.message || err}`;
      correctionsError.hidden = false;
    } finally {
      correctionsApplyAllButton.disabled = false;
    }
  });

  correctionsViewResultsButton.addEventListener("click", function () {
    hideAdminSection();
  });

  // ---- CAM Allocation Overrides ----

  let computedCamRatios = [];   // [{cam_id, division_node, allocation_pct_rev, allocation_pct_gp}]
  let camSearchTerm = "";
  // Pending inline edits: key = "cam_id|division_node" → {cam_id, division_node, pct_rev, pct_gp, note, existing_id}
  const camPending = {};
  let camDivisionTotalProblems = [];

  // Effective % for a row = pending edit (if the field was touched, even
  // to clear it back to blank) > saved override > computed default.
  function getEffectiveCamPct(key, ratio, override, pendingField) {
    const computedField = pendingField === "pct_rev" ? "allocation_pct_rev" : "allocation_pct_gp";
    const pending = camPending[key];
    if (pending && Object.prototype.hasOwnProperty.call(pending, pendingField)) {
      const v = pending[pendingField];
      if (v !== null && v !== undefined) return v;
      return ratio[computedField] !== undefined ? ratio[computedField] : null;
    }
    if (override && override[computedField] !== null && override[computedField] !== undefined) {
      return override[computedField];
    }
    return ratio[computedField] !== undefined ? ratio[computedField] : null;
  }

  // Sharing % across all CAMs assigned to the same Division Node must add
  // up to 100% (both Revenue and GP), otherwise actual $ allocated to that
  // division won't reconcile. Rows with no Division Node (applies to all
  // divisions) are excluded - they aren't part of a specific 100% split.
  function checkCamDivisionTotals(baseRows, overrideMap) {
    const totals = {};
    baseRows.forEach((ratio) => {
      const divisionNode = ratio.division_node;
      if (!divisionNode) return;
      const key = `${ratio.cam_id}|${divisionNode}`;
      const override = overrideMap[key];
      const rev = getEffectiveCamPct(key, ratio, override, "pct_rev");
      const gp = getEffectiveCamPct(key, ratio, override, "pct_gp");
      if (!totals[divisionNode]) totals[divisionNode] = { rev: 0, gp: 0, revCount: 0, gpCount: 0 };
      if (rev !== null && rev !== undefined) { totals[divisionNode].rev += rev; totals[divisionNode].revCount += 1; }
      if (gp !== null && gp !== undefined) { totals[divisionNode].gp += gp; totals[divisionNode].gpCount += 1; }
    });

    const TOLERANCE = 0.01;
    const problems = [];
    Object.keys(totals).sort().forEach((divisionNode) => {
      const t = totals[divisionNode];
      if (t.revCount > 0 && Math.abs(t.rev - 100) > TOLERANCE) {
        problems.push({
          divisionNode,
          message: `Division "${divisionNode}": Revenue Sharing % totals ${t.rev.toFixed(2)}% across all CAMs (must equal 100%).`,
        });
      }
      if (t.gpCount > 0 && Math.abs(t.gp - 100) > TOLERANCE) {
        problems.push({
          divisionNode,
          message: `Division "${divisionNode}": GP Sharing % totals ${t.gp.toFixed(2)}% across all CAMs (must equal 100%).`,
        });
      }
    });

    camDivisionTotalProblems = problems;
    if (problems.length > 0) {
      camDivisionTotalsWarning.innerHTML =
        "<strong>Sharing % must total 100% per Division Node:</strong><br>" +
        problems.map((p) => p.message.replace(/</g, "&lt;")).join("<br>");
      camDivisionTotalsWarning.hidden = false;
    } else {
      camDivisionTotalsWarning.hidden = true;
    }
    return problems;
  }

  async function loadComputedCamRatios() {
    if (!currentRunId) { computedCamRatios = []; return; }
    try {
      const resp = await fetch(`${API_BASE}/${currentRunId}/cam-ratios`, { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        computedCamRatios = data.ratios || [];
      }
    } catch (_err) {
      computedCamRatios = [];
    }
  }

  async function loadCamOverrides() {
    camError.hidden = true;
    Object.keys(camPending).forEach((k) => delete camPending[k]);
    await Promise.all([loadComputedCamRatios(), fetchCamOverrides()]);
    renderCamTable();
  }

  async function fetchCamOverrides() {
    try {
      const resp = await fetch(CAM_API_BASE, { cache: "no-store" });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      const data = await resp.json();
      currentCamOverrides = data.overrides || [];
    } catch (err) {
      camError.textContent = err.message || String(err);
      camError.hidden = false;
    }
  }
  function renderCamTable() {
    const tbody = camTable.querySelector("tbody");
    tbody.innerHTML = "";

    const overrideMap = {};
    currentCamOverrides.forEach((o) => {
      overrideMap[`${o.cam_id}|${o.division_node || ""}`] = o;
    });

    const baseRows = computedCamRatios.length > 0
      ? computedCamRatios
      : currentCamOverrides.map((o) => ({ cam_id: o.cam_id, division_node: o.division_node, allocation_pct_rev: null, allocation_pct_gp: null }));

    currentCamOverrides.forEach((o) => {
      const key = `${o.cam_id}|${o.division_node || ""}`;
      if (!baseRows.find((r) => `${r.cam_id}|${r.division_node || ""}` === key)) {
        baseRows.push({ cam_id: o.cam_id, division_node: o.division_node, allocation_pct_rev: null, allocation_pct_gp: null });
      }
    });

    const visibleRows = camSearchTerm
      ? baseRows.filter((r) =>
          (r.cam_id || "").toLowerCase().includes(camSearchTerm) ||
          (r.division_node || "").toLowerCase().includes(camSearchTerm))
      : baseRows;

    function makeNumInput(key, field, computedVal, overrideVal) {
      const inp = document.createElement("input");
      inp.type = "number"; inp.step = "0.01"; inp.min = "0"; inp.max = "100";
      inp.style.width = "80px"; inp.style.fontSize = "13px";
      inp.placeholder = computedVal !== null && computedVal !== undefined ? String(computedVal) : "";
      // Pre-fill with pending > override > blank
      const pending = camPending[key];
      const val = pending ? pending[field]
                : overrideVal !== null && overrideVal !== undefined ? overrideVal
                : "";
      if (val !== "" && val !== null && val !== undefined) inp.value = val;
      inp.addEventListener("change", function () {
        if (!camPending[key]) {
          const ov = overrideMap[key];
          camPending[key] = {
            cam_id: key.split("|")[0],
            division_node: key.split("|")[1] || null,
            pct_rev: ov ? ov.allocation_pct_rev : null,
            pct_gp:  ov ? ov.allocation_pct_gp  : null,
            note:    ov ? ov.note : null,
            existing_id: ov ? ov.id : null,
          };
        }
        const v = inp.value.trim() === "" ? null : parseFloat(inp.value);
        camPending[key][field] = v;
        updateCamPendingHint();
        checkCamDivisionTotals(baseRows, overrideMap);
      });
      return inp;
    }

    function makeNoteInput(key, overrideNote) {
      const inp = document.createElement("input");
      inp.type = "text"; inp.placeholder = "Add a note…";
      inp.style.width = "160px"; inp.style.fontSize = "13px";
      const pending = camPending[key];
      const val = pending ? pending.note
                : overrideNote !== null && overrideNote !== undefined ? overrideNote
                : "";
      if (val) inp.value = val;
      inp.addEventListener("change", function () {
        if (!camPending[key]) {
          const ov = overrideMap[key];
          camPending[key] = {
            cam_id: key.split("|")[0],
            division_node: key.split("|")[1] || null,
            pct_rev: ov ? ov.allocation_pct_rev : null,
            pct_gp:  ov ? ov.allocation_pct_gp  : null,
            note:    ov ? ov.note : null,
            existing_id: ov ? ov.id : null,
          };
        }
        camPending[key].note = inp.value.trim() === "" ? null : inp.value.trim();
        updateCamPendingHint();
      });
      return inp;
    }

    visibleRows.forEach((ratio) => {
      const key = `${ratio.cam_id}|${ratio.division_node || ""}`;
      const override = overrideMap[key];
      const hasPending = Boolean(camPending[key]);
      const tr = document.createElement("tr");
      if (override) tr.style.background = "#fffbeb";
      if (hasPending) tr.style.outline = "2px solid #f59e0b";

      // CAM ID
      const tdCam = document.createElement("td"); tdCam.textContent = ratio.cam_id; tr.appendChild(tdCam);
      // Division
      const tdDiv = document.createElement("td"); tdDiv.textContent = ratio.division_node || "(all)"; tr.appendChild(tdDiv);
      // Computed Rev %
      const tdCRev = document.createElement("td");
      tdCRev.textContent = ratio.allocation_pct_rev !== null && ratio.allocation_pct_rev !== undefined ? ratio.allocation_pct_rev + "%" : "—";
      tdCRev.style.color = "var(--color-muted)"; tr.appendChild(tdCRev);
      // Override Rev % input
      const tdORev = document.createElement("td");
      tdORev.appendChild(makeNumInput(key, "pct_rev", ratio.allocation_pct_rev, override ? override.allocation_pct_rev : null));
      tr.appendChild(tdORev);
      // Computed GP %
      const tdCGp = document.createElement("td");
      tdCGp.textContent = ratio.allocation_pct_gp !== null && ratio.allocation_pct_gp !== undefined ? ratio.allocation_pct_gp + "%" : "—";
      tdCGp.style.color = "var(--color-muted)"; tr.appendChild(tdCGp);
      // Override GP % input
      const tdOGp = document.createElement("td");
      tdOGp.appendChild(makeNumInput(key, "pct_gp", ratio.allocation_pct_gp, override ? override.allocation_pct_gp : null));
      tr.appendChild(tdOGp);
      // Note
      const tdNote = document.createElement("td");
      tdNote.appendChild(makeNoteInput(key, override ? override.note : null));
      tr.appendChild(tdNote);

      // Actions - only a manually-added override can be removed; there's
      // nothing to delete for a purely computed row.
      const tdActions = document.createElement("td");
      if (override) {
        const deleteBtn = document.createElement("button");
        deleteBtn.type = "button";
        deleteBtn.className = "btn btn-delete";
        deleteBtn.textContent = "Delete";
        deleteBtn.style.fontSize = "12px";
        deleteBtn.addEventListener("click", () => {
          const confirmed = window.confirm(
            `Remove the manually-added override for ${override.cam_id}` +
            (override.division_node ? ` / ${override.division_node}` : " (all divisions)") +
            `? Allocation will revert to the computed value. Click "Apply All Changes" to save this.`
          );
          if (!confirmed) return;
          // Stage the deletion the same way an edit is staged - all-null
          // pending fields with existing_id set tells Apply All Changes to
          // DELETE this override instead of PUT-ing it (see below).
          camPending[key] = {
            cam_id: override.cam_id,
            division_node: override.division_node || null,
            pct_rev: null,
            pct_gp: null,
            note: null,
            existing_id: override.id,
          };
          renderCamTable();
        });
        tdActions.appendChild(deleteBtn);
      }
      tr.appendChild(tdActions);

      tbody.appendChild(tr);
    });

    if (visibleRows.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 8; td.style.textAlign = "center"; td.style.color = "var(--color-muted)";
      td.textContent = camSearchTerm ? "No CAM employees match your search."
        : currentRunId ? "No CAM employees found in this run's BP data."
        : "Run the pipeline first to see computed allocation ratios.";
      tr.appendChild(td); tbody.appendChild(tr);
    }

    updateCamPendingHint();
    checkCamDivisionTotals(baseRows, overrideMap);
  }

  function updateCamPendingHint() {
    const count = Object.keys(camPending).length;
    if (count === 0) {
      camPendingHint.textContent = "";
      camApplyAllButton.hidden = true;
      camDiscardButton.hidden = true;
    } else {
      camPendingHint.textContent = `${count} row(s) with pending changes. Click "Apply All Changes" to save and recalculate.`;
      camApplyAllButton.hidden = false;
      camDiscardButton.hidden = false;
    }
  }

  function openCamModal(override, computedRatio) {
    camFormError.hidden = true;
    camForm.reset();
    editingCamOverrideId = override ? override.id : null;
    camModalTitle.textContent = override ? "Edit CAM Allocation Override" : "Add CAM Allocation Override";

    // Pre-fill from override first; fall back to computed ratio
    camCamIdInput.value = (override && override.cam_id) || (computedRatio && computedRatio.cam_id) || "";
    camEmployeeNameInput.value = (override && override.employee_name) || "";
    camDivisionNodeInput.value = (override && override.division_node) || (computedRatio && computedRatio.division_node) || "";
    // For percentages: show override value if editing; show computed value as starting point for new overrides
    const defaultRev = override ? override.allocation_pct_rev : (computedRatio ? computedRatio.allocation_pct_rev : null);
    const defaultGp  = override ? override.allocation_pct_gp  : (computedRatio ? computedRatio.allocation_pct_gp  : null);
    camPctRevInput.value = defaultRev !== null && defaultRev !== undefined ? defaultRev : "";
    camPctGpInput.value  = defaultGp  !== null && defaultGp  !== undefined ? defaultGp  : "";
    camNoteInput.value = (override && override.note) || "";
    camModal.hidden = false;
  }

  function closeCamModal() {
    camModal.hidden = true;
    editingCamOverrideId = null;
  }

  camModalClose.addEventListener("click", closeCamModal);
  camFormCancel.addEventListener("click", closeCamModal);
  camModal.addEventListener("click", function (e) {
    if (e.target === camModal) closeCamModal();
  });

  camForm.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target && e.target.tagName !== "BUTTON") e.preventDefault();
  });

  camAddButton.addEventListener("click", function () {
    openCamModal(null, null);
  });

  camSearchInput.addEventListener("input", function () {
    camSearchTerm = camSearchInput.value.trim().toLowerCase();
    renderCamTable();
  });

  camDiscardButton.addEventListener("click", function () {
    Object.keys(camPending).forEach((k) => delete camPending[k]);
    renderCamTable();
  });

  camApplyAllButton.addEventListener("click", async function () {
    camError.hidden = true;

    if (camDivisionTotalProblems.length > 0) {
      const pendingDivisions = new Set(
        Object.values(camPending)
          .map((entry) => entry.division_node)
          .filter(Boolean)
      );
      const blockingProblems = camDivisionTotalProblems.filter((p) =>
        pendingDivisions.has(p.divisionNode)
      );
      if (blockingProblems.length > 0) {
        camError.textContent =
          "Fix the Sharing % totals before saving: " +
          blockingProblems.map((p) => p.message).join(" ");
        camError.hidden = false;
        return;
      }
    }

    camApplyAllButton.disabled = true;
    camApplyAllButton.textContent = "Saving…";

    try {
      for (const [, entry] of Object.entries(camPending)) {
        const isEmpty = entry.pct_rev === null && entry.pct_gp === null && !entry.note;

        if (isEmpty) {
          if (!entry.existing_id) continue; // nothing entered, nothing to create

          // All fields cleared for a previously-saved override (via the
          // Delete button, or by manually clearing every field) - remove
          // it instead of silently ignoring it, so it actually goes away
          // rather than reverting the row to computed on screen while the
          // override still exists in storage.
          const delResp = await fetch(
            `${CAM_API_BASE}/${entry.existing_id}?changed_by=${encodeURIComponent(currentUsername())}`,
            { method: "DELETE" }
          );
          if (!delResp.ok && delResp.status !== 204) throw new Error(await readErrorDetail(delResp));
          continue;
        }

        const payload = {
          cam_id: entry.cam_id,
          division_node: entry.division_node || null,
          allocation_pct_rev: entry.pct_rev,
          allocation_pct_gp: entry.pct_gp,
          note: entry.note || null,
          changed_by: currentUsername(),
        };
        const url = entry.existing_id ? `${CAM_API_BASE}/${entry.existing_id}` : CAM_API_BASE;
        const method = entry.existing_id ? "PUT" : "POST";
        const resp = await fetch(url, {
          method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error(await readErrorDetail(resp));
      }
      // Clear pending
      Object.keys(camPending).forEach((k) => delete camPending[k]);
      await loadCamOverrides();
      // Re-run calculations
      await camRecalculateAndShowResults(false);
    } catch (err) {
      camError.textContent = `Failed to save: ${err.message || err}`;
      camError.hidden = false;
    } finally {
      camApplyAllButton.disabled = false;
      camApplyAllButton.textContent = "Apply All Changes";
    }
  });

  camViewResultsButton.addEventListener("click", function () {
    hideAdminSection();
  });

  camForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    camFormError.hidden = true;

    const clickedApply = Boolean(
      e.submitter && e.submitter.id === "cam-form-apply"
    );

    const pctRevRaw = camPctRevInput.value.trim();
    const pctGpRaw = camPctGpInput.value.trim();
    const noteRaw = camNoteInput.value.trim();

    if (!pctRevRaw && !pctGpRaw && !noteRaw) {
      camFormError.textContent = "Enter Allocation % Revenue, Allocation % GP, or a note.";
      camFormError.hidden = false;
      return;
    }

    const payload = {
      cam_id: camCamIdInput.value.trim(),
      employee_name: camEmployeeNameInput.value.trim() || null,
      division_node: camDivisionNodeInput.value.trim() || null,
      allocation_pct_rev: pctRevRaw !== "" ? parseFloat(pctRevRaw) : null,
      allocation_pct_gp: pctGpRaw !== "" ? parseFloat(pctGpRaw) : null,
      note: camNoteInput.value.trim() || null,
      changed_by: currentUsername(),
    };

    if (!payload.cam_id) {
      camFormError.textContent = "CAM ID is required.";
      camFormError.hidden = false;
      return;
    }

    try {
      const url = editingCamOverrideId
        ? `${CAM_API_BASE}/${editingCamOverrideId}`
        : CAM_API_BASE;
      const method = editingCamOverrideId ? "PUT" : "POST";
      const resp = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      closeCamModal();
      await loadCamOverrides();
      await camRecalculateAndShowResults(clickedApply);
    } catch (err) {
      camFormError.textContent = err.message || String(err);
      camFormError.hidden = false;
    }
  });

  async function camRecalculateAndShowResults(navigateToResults) {
    if (!currentRunId) {
      camStatus.textContent =
        "No active run yet \u2014 this will apply the next time you run the pipeline.";
      camStatus.hidden = false;
      return;
    }

    camStatus.textContent = "Recalculating SIP results with the updated CAM allocations\u2026";
    camStatus.hidden = false;

    try {
      const calculationParams = getCalculationParameters("default");
      const resp = await fetch(`${API_BASE}/${currentRunId}/calculations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(calculationParams),
      });
      if (!resp.ok) throw new Error(await readErrorDetail(resp));
      const result = await resp.json();
      populateRoleSelect(result.enabled_roles, result.role_row_counts);
      await loadResults(roleSelect.value);
      persistRun(currentRunId, result.enabled_roles, result.role_row_counts);

      if (navigateToResults) {
        camStatus.hidden = true;
        hideAdminSection();
        return;
      }

      camStatus.textContent = "Recalculated. Click \u201cView Results\u201d to see them.";
      camStatus.hidden = false;
      camViewResultsButton.hidden = false;
    } catch (err) {
      camStatus.hidden = true;
      camError.textContent = `Recalculation failed: ${err.message || err}`;
      camError.hidden = false;
    }
  }

  // ---- Admin password gate (separate from the main login) ----
  function showAdminPasswordGate() {
    hideAllMainSections();
    adminPasswordError.hidden = true;
    adminPasswordForm.reset();
    adminPasswordSection.hidden = false;
  }

  function hideAdminPasswordGate() {
    hideAllMainSections();

    if (currentRunId) {
      resultsSection.hidden = false;
    } else {
      uploadSection.hidden = false;
    }
  }

  adminButton.addEventListener("click", async function () {
    if (sessionStorage.getItem(ADMIN_AUTH_STORAGE_KEY) === "true") {
      await showAdminSection();
    } else {
      showAdminPasswordGate();
    }
  });

  adminPasswordForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    const password = document.getElementById("admin-password-input").value;

    if (password !== ADMIN_PASSWORD) {
      adminPasswordError.textContent = "Incorrect admin password.";
      adminPasswordError.hidden = false;
      return;
    }

    sessionStorage.setItem(ADMIN_AUTH_STORAGE_KEY, "true");
    adminPasswordSection.hidden = true;
    await showAdminSection();
  });

  adminPasswordCancelButton.addEventListener("click", hideAdminPasswordGate);

  adminBackButton.addEventListener("click", hideAdminSection);

  adminRoleSelect.addEventListener("change", function () {
    renderAdminParameters(adminRoleSelect.value);
  });

  adminResetButton.addEventListener("click", function () {
    const role = adminRoleSelect.value;
    roleParameterState[role] = { ...DEFAULT_PARAMETERS };
    renderAdminParameters(role);
  });

  async function applyParameterChanges() {
    if (!currentRunId) {
      parametersStatus.textContent =
        "No active run yet - parameters will apply automatically when you run the pipeline.";
      parametersStatus.hidden = false;
      return;
    }

    parametersStatus.textContent = "Applying parameter changes...";
    parametersStatus.hidden = false;
    parametersError.hidden = true;
    applyParametersButton.disabled = true;

    try {
      const calculationParams = getCalculationParameters("default");
      
      // Log which parameters are being applied
      const appliedParams = Object.entries(calculationParams)
        .map(([key, value]) => `${formatParameterLabel(key)}: ${value}`)
        .join(", ");
      
      console.log("Applying parameters:", appliedParams);

      const response = await fetch(
        `${API_BASE}/${currentRunId}/calculations/apply-parameters`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(calculationParams),
        }
      );

      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }

      const calculationsResult = await response.json();
      populateRoleSelect(
        calculationsResult.enabled_roles,
        calculationsResult.role_row_counts
      );
      await loadResults(roleSelect.value);
      persistRun(
        currentRunId,
        calculationsResult.enabled_roles,
        calculationsResult.role_row_counts
      );

      parametersStatus.textContent = "Parameters applied successfully.";
      parametersStatus.hidden = false;
      parametersError.hidden = true;

      // The top-of-page badge ("Running calculations for Q# FY####") is
      // only ever loaded once from the GLOBAL config default
      // (GET /parameters), which this per-run override never changes - so
      // re-fetching it here would still show the old quarter. Update the
      // badge directly from what was actually just applied instead.
      // fiscal_year isn't an admin-editable field (only quarter is), so
      // reuse the fiscal year already shown rather than expecting it in
      // calculationParams.
      if (calculationParams.quarter && calculationPeriodFiscalYear) {
        calculationPeriodBadge.textContent =
          `Running calculations for ${calculationParams.quarter} FY${calculationPeriodFiscalYear}`;
        calculationPeriodBadge.hidden = false;
      }
    } catch (err) {
      parametersStatus.hidden = true;
      parametersError.textContent = `Failed to apply parameters: ${err.message || err}`;
      parametersError.hidden = false;
    } finally {
      applyParametersButton.disabled = false;
    }
  }

  applyParametersButton.addEventListener("click", applyParameterChanges);

  populateAdminRoleSelect();

  loginForm.addEventListener("submit", function (event) {
    event.preventDefault();
    loginError.hidden = true;

    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;

    if (!username || password !== SHARED_PASSWORD) {
      loginError.textContent = "Incorrect password.";
      loginError.hidden = false;
      return;
    }

    sessionStorage.setItem(AUTH_STORAGE_KEY, "true");
    sessionStorage.setItem(USERNAME_STORAGE_KEY, username);
    loginForm.reset();
    showAppShell();
  });

  logoutButton.addEventListener("click", function () {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    sessionStorage.removeItem(USERNAME_STORAGE_KEY);
    sessionStorage.removeItem(ADMIN_AUTH_STORAGE_KEY);
    sessionStorage.removeItem(ADMIN_OPEN_KEY);
    sessionStorage.removeItem(ADMIN_TAB_KEY);
    sessionStorage.removeItem(HR_DONE_KEY);
    resetUI();
    showLoginScreen();
  });

  window.addEventListener("pageshow", function () {
    if (sessionStorage.getItem(AUTH_STORAGE_KEY) !== "true") {
      resetUI();
      showLoginScreen();
    }
  });

  // ---- Startup: skip the login screen only if already logged in this
  // browser session (sessionStorage is cleared when the tab/browser closes,
  // which is fine for a demo login). ----
  if (sessionStorage.getItem(AUTH_STORAGE_KEY) === "true") {
    showAppShell();
  } else {
    showLoginScreen();
  }
})();
