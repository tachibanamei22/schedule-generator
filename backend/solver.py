"""
OR-Tools CP-SAT Constraint Solver for WFM Schedule Generation.

Supports any number of shift codes read dynamically from the WFM data.
Constraints are parsed from the Regulation sheet via GPT (or hardcoded defaults).

Objective: minimise the gap between hourly forecast demand and actual staffing
coverage, while keeping OFF-day counts fair across agents.
"""
from ortools.sat.python import cp_model
from data_parser import WFMData, Agent, ShiftCode, LeaveRequest, ForecastData
from typing import Dict, List, Tuple, Optional
import json


class ScheduleSolver:
    def __init__(self, wfm_data: WFMData):
        self.data = wfm_data
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()

        # All schedulable codes: [OFF, <working shifts…>, Leave, Resign]
        self.working_shifts: List[str] = self._get_working_shifts()
        self.shift_indices: Dict[str, int] = {
            code: i for i, code in enumerate(self.working_shifts)
        }
        self.off_index: int = self.shift_indices.get('OFF', 0)

        # Decision variables: (agent_idx, day_idx) → IntVar in [0, num_shifts)
        self.schedule_vars: Dict[Tuple[int, int], cp_model.IntVar] = {}

        # Shared boolean assignment vars: (a, d, s_idx) → BoolVar
        # is_on_shift[(a, d, s)] = 1  iff  schedule_vars[(a,d)] == s
        self.is_on_shift: Dict[Tuple[int, int, int], cp_model.IntVar] = {}

        # Results
        self.result_schedule: Dict[str, Dict[str, str]] = {}
        self.solve_status = None
        self.solve_time = 0.0

    # ──────────────────────────────────────────────────────────────────────────
    # Shift list helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_working_shifts(self) -> List[str]:
        """
        Build the ordered list of schedulable codes:
          index 0 = OFF
          indices 1..N = actual working shifts (non-leave, non-OFF), sorted by start_time
          last two   = Leave, Resign
        """
        working = []
        for code, sc in self.data.shift_codes.items():
            if not sc.is_leave and code not in ('OFF', 'Day Off') and sc.start_time is not None:
                working.append((sc.start_time, code))

        # Sort by start time so the order is deterministic
        working.sort()
        codes = ['OFF'] + [code for _, code in working] + ['Leave', 'Resign']
        return codes

    def _shift_period(self, code: str) -> str:
        """Return 'morning', 'afternoon', or 'night' for a shift code."""
        if code in ('OFF', 'Leave', 'Resign'):
            return 'off'
        sc = self.data.shift_codes.get(code)
        if sc:
            return sc.shift_period
        return 'morning'

    def _hours_covered(self, code: str):
        """Return the set of hours (0-23) covered by a shift code."""
        if code in ('OFF', 'Leave', 'Resign'):
            return set()
        sc = self.data.shift_codes.get(code)
        return set(sc.hours_covered) if sc else set()

    # ──────────────────────────────────────────────────────────────────────────
    # Model building
    # ──────────────────────────────────────────────────────────────────────────

    def build_model(self, parsed_rules=None):
        """Build the complete CP-SAT model."""
        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)
        num_shifts = len(self.working_shifts)

        # --- Create integer decision variables ---
        for a in range(num_agents):
            for d in range(num_days):
                self.schedule_vars[(a, d)] = self.model.NewIntVar(
                    0, num_shifts - 1, f'a{a}_d{d}'
                )

        # --- Create shared boolean assignment variables (reused by all constraints) ---
        for a in range(num_agents):
            for d in range(num_days):
                for s in range(num_shifts):
                    v = self.model.NewBoolVar(f'on_{a}_{d}_{s}')
                    self.model.Add(self.schedule_vars[(a, d)] == s).OnlyEnforceIf(v)
                    self.model.Add(self.schedule_vars[(a, d)] != s).OnlyEnforceIf(v.Not())
                    self.is_on_shift[(a, d, s)] = v

        # --- Hard constraints ---
        self._add_leave_constraints()

        if parsed_rules:
            self._apply_dynamic_rules(parsed_rules)
        else:
            self._add_max_consecutive_work_days(max_days=6)
            self._add_max_consecutive_off_days(max_days=2)
            self._add_shift_consistency_constraints()
            self._add_night_shift_female_restriction()

        # --- Objective ---
        self._add_coverage_objective()

    # ──────────────────────────────────────────────────────────────────────────
    # Dynamic rule dispatcher
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_dynamic_rules(self, parsed_rules):
        dispatch = {
            'max_consecutive_work_days': lambda r: self._add_max_consecutive_work_days(
                max_days=r.params.get('limit', 6)),
            'max_consecutive_off_days':  lambda r: self._add_max_consecutive_off_days(
                max_days=r.params.get('limit', 2)),
            'no_shift_jumping':          lambda r: self._add_shift_consistency_constraints(),
            'gender_shift_restriction':  lambda r: self._add_night_shift_female_restriction(
                gender=r.params.get('gender', 'F'),
                shift_period=r.params.get('shift_period', 'night')),
            'max_shifts_per_week':       lambda r: self._add_max_shifts_per_week(
                shift_period=r.params.get('shift_period', 'night'),
                limit=r.params.get('limit', 3)),
            'min_off_days_per_week':     lambda r: self._add_min_off_days_per_week(
                limit=r.params.get('limit', 1)),
        }
        applied = 0
        for rule in parsed_rules:
            if not rule.enforceable:
                print(f"  ⓘ Skipping (display-only): {rule.original_text}")
                continue
            handler = dispatch.get(rule.type)
            if handler:
                try:
                    handler(rule)
                    applied += 1
                    print(f"  ✓ Applied: {rule.type} — {rule.original_text}")
                except Exception as e:
                    print(f"  ✗ Failed {rule.type}: {e}")
            else:
                print(f"  ⓘ Unknown rule type: {rule.type}")
        print(f"Applied {applied}/{len(parsed_rules)} regulation constraints")

    # ──────────────────────────────────────────────────────────────────────────
    # Constraint implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _is_off(self, a: int, d: int):
        return self.is_on_shift[(a, d, self.off_index)]

    def _is_working(self, a: int, d: int):
        """Returns a BoolVar that is 1 when agent is on any working shift (not OFF/Leave/Resign)."""
        leave_idx  = self.shift_indices.get('Leave',  len(self.working_shifts) - 2)
        resign_idx = self.shift_indices.get('Resign', len(self.working_shifts) - 1)
        non_working = {self.off_index, leave_idx, resign_idx}

        working_bool = self.model.NewBoolVar(f'iswork_{a}_{d}')
        is_working_vars = [
            self.is_on_shift[(a, d, s)]
            for s in range(len(self.working_shifts))
            if s not in non_working
        ]
        if is_working_vars:
            self.model.AddBoolOr(is_working_vars).OnlyEnforceIf(working_bool)
            self.model.AddBoolAnd([v.Not() for v in is_working_vars]).OnlyEnforceIf(working_bool.Not())
        else:
            self.model.Add(working_bool == 0)
        return working_bool

    def _add_leave_constraints(self):
        """Lock leave/off days and block Leave/Resign for everyone who didn't request it."""
        leave_idx  = self.shift_indices.get('Leave',  len(self.working_shifts) - 2)
        resign_idx = self.shift_indices.get('Resign', len(self.working_shifts) - 1)
        leave_locked: set = set()

        for req in self.data.leave_requests:
            agent_idx = next(
                (i for i, ag in enumerate(self.data.agents) if ag.id == req.employee_id),
                None
            )
            if agent_idx is None:
                continue

            date_str = req.date.strftime('%Y-%m-%d')
            day_idx = next(
                (d for d, ds in enumerate(self.data.dates) if ds == date_str),
                None
            )
            if day_idx is None:
                continue

            if req.leave_type == 'Leave':
                self.model.Add(self.schedule_vars[(agent_idx, day_idx)] == leave_idx)
            elif req.leave_type in ('Off', 'OFF'):
                self.model.Add(self.schedule_vars[(agent_idx, day_idx)] == self.off_index)
            leave_locked.add((agent_idx, day_idx))

        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)
        for a in range(num_agents):
            for d in range(num_days):
                if (a, d) not in leave_locked:
                    self.model.Add(self.schedule_vars[(a, d)] != leave_idx)
                    self.model.Add(self.schedule_vars[(a, d)] != resign_idx)

    def _add_max_consecutive_work_days(self, max_days: int = 6):
        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)
        for a in range(num_agents):
            for d in range(num_days - max_days):
                # In any window of (max_days+1), at least one must be OFF
                self.model.Add(
                    sum(self._is_off(a, dd) for dd in range(d, d + max_days + 1)) >= 1
                )

    def _add_max_consecutive_off_days(self, max_days: int = 2):
        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)
        for a in range(num_agents):
            for d in range(num_days - max_days):
                # In any window of (max_days+1), at least one must be non-OFF
                self.model.Add(
                    sum(self._is_working(a, dd) for dd in range(d, d + max_days + 1)) >= 1
                )

    def _add_shift_consistency_constraints(self):
        """
        No shift jumping: if an agent works a given shift period (morning/afternoon/night)
        on day d, and works on day d+1, day d+1 must be the same period.
        Transition through OFF is allowed.
        """
        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)

        # Build period → set of shift indices
        period_indices: Dict[str, List[int]] = {}
        for s_idx, code in enumerate(self.working_shifts):
            p = self._shift_period(code)
            if p != 'off':
                period_indices.setdefault(p, []).append(s_idx)

        if len(period_indices) <= 1:
            return  # nothing to enforce

        leave_idx  = self.shift_indices.get('Leave',  len(self.working_shifts) - 2)
        resign_idx = self.shift_indices.get('Resign', len(self.working_shifts) - 1)
        non_working = {self.off_index, leave_idx, resign_idx}

        for a in range(num_agents):
            for d in range(num_days - 1):
                for period, idxs in period_indices.items():
                    # is_in_period_today = OR(is_on_shift[a,d,s] for s in idxs)
                    is_in_period = self.model.NewBoolVar(f'period_{period}_{a}_{d}')
                    period_vars  = [self.is_on_shift[(a, d, s)] for s in idxs]
                    self.model.AddBoolOr(period_vars).OnlyEnforceIf(is_in_period)
                    self.model.AddBoolAnd([v.Not() for v in period_vars]).OnlyEnforceIf(is_in_period.Not())

                    # is_working_tomorrow
                    working_tomorrow = [
                        self.is_on_shift[(a, d + 1, s)]
                        for s in range(len(self.working_shifts))
                        if s not in non_working
                    ]
                    if not working_tomorrow:
                        continue

                    is_work_tom = self.model.NewBoolVar(f'wt_{period}_{a}_{d}')
                    self.model.AddBoolOr(working_tomorrow).OnlyEnforceIf(is_work_tom)
                    self.model.AddBoolAnd([v.Not() for v in working_tomorrow]).OnlyEnforceIf(is_work_tom.Not())

                    # If today is this period AND tomorrow is working → tomorrow must also be this period
                    both = self.model.NewBoolVar(f'both_{period}_{a}_{d}')
                    self.model.AddBoolAnd([is_in_period, is_work_tom]).OnlyEnforceIf(both)
                    self.model.AddBoolOr([is_in_period.Not(), is_work_tom.Not()]).OnlyEnforceIf(both.Not())

                    # tomorrow must be in same period
                    other_period_vars = [
                        self.is_on_shift[(a, d + 1, s)]
                        for other_p, other_idxs in period_indices.items()
                        if other_p != period
                        for s in other_idxs
                    ]
                    if other_period_vars:
                        self.model.AddBoolAnd([v.Not() for v in other_period_vars]).OnlyEnforceIf(both)

    def _add_night_shift_female_restriction(self, gender: str = 'F', shift_period: str = 'night'):
        """Restrict agents of given gender from working shifts of given period."""
        restricted_idxs = [
            s_idx for s_idx, code in enumerate(self.working_shifts)
            if self._shift_period(code) == shift_period
        ]
        if not restricted_idxs:
            return

        num_days = len(self.data.dates)
        for a, agent in enumerate(self.data.agents):
            if agent.gender == gender:
                for d in range(num_days):
                    for s_idx in restricted_idxs:
                        self.model.Add(self.schedule_vars[(a, d)] != s_idx)

    def _add_max_shifts_per_week(self, shift_period: str = 'night', limit: int = 3):
        target_idxs = [
            s_idx for s_idx, code in enumerate(self.working_shifts)
            if self._shift_period(code) == shift_period
        ]
        if not target_idxs:
            return

        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)
        for a in range(num_agents):
            for start in range(0, num_days - 6):
                week_vars = [
                    self.is_on_shift[(a, d, s)]
                    for d in range(start, start + 7)
                    for s in target_idxs
                ]
                self.model.Add(sum(week_vars) <= limit)

    def _add_min_off_days_per_week(self, limit: int = 1):
        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)
        for a in range(num_agents):
            for start in range(0, num_days - 6):
                self.model.Add(
                    sum(self._is_off(a, d) for d in range(start, start + 7)) >= limit
                )

    # ──────────────────────────────────────────────────────────────────────────
    # Coverage objective
    # ──────────────────────────────────────────────────────────────────────────

    def _add_coverage_objective(self):
        """Route to the appropriate objective based on available demand data."""
        if self.data.shift_demand:
            self._add_shift_demand_objective()
        else:
            self._add_hourly_coverage_objective()

    def _add_hourly_coverage_objective(self):
        """Original hourly-forecast-based coverage objective (kept for backward compat)."""
        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)

        # Precompute covered hours per shift index (constant)
        shift_hours: List[set] = [
            self._hours_covered(code) for code in self.working_shifts
        ]

        # Group shift indices by hour they cover → hours_to_shifts[hour] = [s_idx, ...]
        hours_to_shifts: Dict[int, List[int]] = {}
        for hour in range(24):
            covering = [s for s, hrs in enumerate(shift_hours) if hour in hrs]
            if covering:
                hours_to_shifts[hour] = covering

        total_penalty = []

        for d in range(num_days):
            date_str     = self.data.dates[d]
            forecast_day = self.data.forecast.requirements.get(date_str, {})

            for hour, covering_idxs in hours_to_shifts.items():
                demand = forecast_day.get(hour, 0)
                if demand == 0:
                    continue

                # coverage = number of agents on a shift that covers this hour
                # = sum over agents of (sum over covering shifts of is_on_shift[a,d,s])
                coverage_sum = sum(
                    self.is_on_shift[(a, d, s)]
                    for a in range(num_agents)
                    for s in covering_idxs
                )

                count = self.model.NewIntVar(0, num_agents, f'cnt_{d}_{hour}')
                self.model.Add(count == coverage_sum)

                dev     = self.model.NewIntVar(-num_agents, num_agents, f'dev_{d}_{hour}')
                abs_dev = self.model.NewIntVar(0, num_agents, f'adev_{d}_{hour}')
                self.model.Add(dev == count - demand)
                self.model.AddAbsEquality(abs_dev, dev)
                total_penalty.append(abs_dev)

        # Fair OFF-day distribution (~1 day off per 7 working days)
        target_off = max(1, num_days // 7)
        for a in range(num_agents):
            off_count = self.model.NewIntVar(0, num_days, f'offc_{a}')
            self.model.Add(off_count == sum(self._is_off(a, d) for d in range(num_days)))

            dev_off     = self.model.NewIntVar(-num_days, num_days, f'devo_{a}')
            abs_dev_off = self.model.NewIntVar(0, num_days, f'adevo_{a}')
            self.model.Add(dev_off == off_count - target_off)
            self.model.AddAbsEquality(abs_dev_off, dev_off)
            total_penalty.append(abs_dev_off)

        self.model.Minimize(sum(total_penalty))

    def _add_shift_demand_objective(self):
        """
        When shift_demand is set: minimise |actual_assigned(shift, day) - target(shift, day)|
        for every (shift, day) pair, plus a fairness penalty for OFF-day distribution.
        """
        num_agents = len(self.data.agents)
        num_days   = len(self.data.dates)

        total_penalty = []

        for s_idx, code in enumerate(self.working_shifts):
            if code in ('OFF', 'Leave', 'Resign'):
                continue
            demands = self.data.shift_demand.get(code, [])
            for d in range(num_days):
                target = int(demands[d]) if d < len(demands) else 0

                actual_sum = sum(self.is_on_shift[(a, d, s_idx)] for a in range(num_agents))
                count = self.model.NewIntVar(0, num_agents, f'cnt_{s_idx}_{d}')
                self.model.Add(count == actual_sum)

                dev     = self.model.NewIntVar(-num_agents, num_agents, f'dev_{s_idx}_{d}')
                abs_dev = self.model.NewIntVar(0, num_agents,            f'adev_{s_idx}_{d}')
                self.model.Add(dev == count - target)
                self.model.AddAbsEquality(abs_dev, dev)
                total_penalty.append(abs_dev)

        # Fair OFF-day distribution (~1 day off per 7 working days)
        target_off = max(1, num_days // 7)
        for a in range(num_agents):
            off_count   = self.model.NewIntVar(0, num_days, f'offc_{a}')
            self.model.Add(off_count == sum(self._is_off(a, d) for d in range(num_days)))
            dev_off     = self.model.NewIntVar(-num_days, num_days, f'devo_{a}')
            abs_dev_off = self.model.NewIntVar(0, num_days,          f'adevo_{a}')
            self.model.Add(dev_off == off_count - target_off)
            self.model.AddAbsEquality(abs_dev_off, dev_off)
            total_penalty.append(abs_dev_off)

        self.model.Minimize(sum(total_penalty))

    # ──────────────────────────────────────────────────────────────────────────
    # Solve & extract
    # ──────────────────────────────────────────────────────────────────────────

    def solve(self, time_limit_seconds: int = 60) -> bool:
        self.solver.parameters.max_time_in_seconds = time_limit_seconds
        self.solver.parameters.num_workers = 4

        status = self.solver.Solve(self.model)
        self.solve_status = status
        self.solve_time   = self.solver.WallTime()

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self._extract_results()
            return True
        return False

    def _extract_results(self):
        self.result_schedule = {}
        for a, agent in enumerate(self.data.agents):
            agent_sched = {}
            for d, date_str in enumerate(self.data.dates):
                s_idx = self.solver.Value(self.schedule_vars[(a, d)])
                code  = self.working_shifts[s_idx]

                # Always store the shift code (e.g. "P1", "M3", "OFF") — not the start time
                agent_sched[date_str] = code

            self.result_schedule[agent.id] = agent_sched

    def get_results_json(self) -> dict:
        agents_data = [
            {
                'id':       agent.id,
                'name':     agent.name,
                'role':     agent.role,
                'channel':  agent.channel,
                'gender':   agent.gender,
                'skill':    getattr(agent, 'skill', ''),
                'site':     getattr(agent, 'site', ''),
                'religion': getattr(agent, 'religion', ''),
                'schedule': self.result_schedule.get(agent.id, {}),
            }
            for agent in self.data.agents
        ]

        return {
            'agents':       agents_data,
            'dates':        self.data.dates,
            'shifts':       self.working_shifts,
            'shift_codes':  self._shift_codes_json(),
            'regulations':  self.data.regulations,
            'coverage':     self._calculate_coverage(),
            'solve_status': 'OPTIMAL' if self.solve_status == cp_model.OPTIMAL else 'FEASIBLE',
            'solve_time':   round(self.solve_time, 2),
            'shift_demand': dict(self.data.shift_demand),
        }

    def _shift_codes_json(self) -> dict:
        """Return shift code metadata for the frontend legend."""
        result = {}
        for code in self.working_shifts:
            if code in ('OFF', 'Leave', 'Resign'):
                result[code] = {'period': 'off', 'label': code, 'time': ''}
                continue
            sc = self.data.shift_codes.get(code)
            if sc and sc.start_time:
                label = sc.start_time.strftime('%H:%M')
                if sc.end_time:
                    label = f"{sc.start_time.strftime('%H:%M')}-{sc.end_time.strftime('%H:%M')}"
                result[code] = {
                    'period': sc.shift_period,
                    'label':  label,
                    'time':   sc.start_time.strftime('%H:%M'),
                }
        return result

    def _calculate_coverage(self) -> dict:
        coverage = {}
        # Collect per-shift counts for stats
        shift_hours = [self._hours_covered(code) for code in self.working_shifts]

        for d, date_str in enumerate(self.data.dates):
            # Count agents per shift period
            period_counts: Dict[str, int] = {}
            off_count = leave_count = total_working = 0

            for agent in self.data.agents:
                code = self.result_schedule.get(agent.id, {}).get(date_str, 'OFF')
                if code == 'OFF':
                    off_count += 1
                elif code in ('Leave', 'Resign'):
                    leave_count += 1
                else:
                    total_working += 1
                    sc = self.data.shift_codes.get(code)
                    if sc:
                        period = sc.shift_period
                        period_counts[period] = period_counts.get(period, 0) + 1

            # Peak forecast demand for the day
            day_forecast = self.data.forecast.requirements.get(date_str, {})
            peak_demand  = max(day_forecast.values()) if day_forecast else 0

            # Sum shift demand for this day
            day_demand_total = 0
            for code, demands in self.data.shift_demand.items():
                day_demand_total += demands[d] if d < len(demands) else 0

            coverage[date_str] = {
                'date':           date_str,
                'total_working':  total_working,
                'off_count':      off_count,
                'leave_count':    leave_count,
                'forecast_demand': day_demand_total if self.data.shift_demand else peak_demand,
                'demand_total':   day_demand_total,
                'gap':            day_demand_total - total_working,
                **{f'{p}_count': c for p, c in period_counts.items()},
            }

        return coverage
