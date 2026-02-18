"""
OR-Tools CP-SAT Constraint Solver for WFM Schedule Generation.

Constraints (from Regulation sheet):
1. Max 6 consecutive working days (ideal: 5 work + 2 off)
2. Consistent shift patterns (avoid shift jumping)
3. Max 2 consecutive days off
4. Night-shift restrictions for female agents

Objective: Minimize gap between forecast staffing needs and scheduled coverage.
"""
from ortools.sat.python import cp_model
from data_parser import WFMData, Agent, ShiftCode, LeaveRequest, ForecastData
from datetime import datetime, time
from typing import Dict, List, Tuple, Optional
import json


class ScheduleSolver:
    def __init__(self, wfm_data: WFMData):
        self.data = wfm_data
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        
        # Filter to working shift codes only (for Call channel)
        # Based on expected result, the main shifts used are 03:00 (night) and 20:00 (evening)
        # Plus OFF, Leave, Resign
        self.working_shifts = self._get_working_shifts()
        self.shift_indices = {code: i for i, code in enumerate(self.working_shifts)}
        self.off_index = self.shift_indices.get('OFF', 0)
        
        # Decision variables: schedule[agent_idx][day_idx] = shift_index
        self.schedule_vars: Dict[Tuple[int, int], cp_model.IntVar] = {}
        
        # Results
        self.result_schedule: Dict[str, Dict[str, str]] = {}
        self.solve_status = None
        self.solve_time = 0
    
    def _get_working_shifts(self) -> List[str]:
        """Get list of shift codes relevant for Call channel scheduling."""
        # Based on expected result, Call channel uses:
        # 03:00 shift, 20:00 shift, OFF, Leave, Resign
        # Map these to actual shift codes from the Shift Code sheet
        
        relevant_shifts = ['OFF']  # index 0 = OFF
        
        # Find shifts that start at 03:00 (night shift)
        for code, shift in self.data.shift_codes.items():
            if shift.start_time and shift.start_time.hour == 3 and shift.start_time.minute == 0:
                if not shift.is_leave:
                    relevant_shifts.append(code)
                    break
        
        # If no 03:00 shift found, use P37 (03:00-12:00)
        if len(relevant_shifts) == 1:
            relevant_shifts.append('P37')
        
        # Find shifts that start at 20:00 (evening shift)
        for code, shift in self.data.shift_codes.items():
            if shift.start_time and shift.start_time.hour == 20 and shift.start_time.minute == 0:
                if not shift.is_leave:
                    relevant_shifts.append(code)
                    break
        
        # If no 20:00 shift found, use M5 (20:00-05:00)
        if len(relevant_shifts) == 2:
            relevant_shifts.append('M5')
        
        # Add Leave and Resign
        relevant_shifts.append('Leave')
        relevant_shifts.append('Resign')
        
        return relevant_shifts
    
    def build_model(self):
        """Build the complete CP-SAT model."""
        num_agents = len(self.data.agents)
        num_days = len(self.data.dates)
        num_shifts = len(self.working_shifts)
        
        # --- Create decision variables ---
        for a in range(num_agents):
            for d in range(num_days):
                self.schedule_vars[(a, d)] = self.model.NewIntVar(
                    0, num_shifts - 1,
                    f'agent_{a}_day_{d}'
                )
        
        # --- Apply hard constraints ---
        self._add_leave_constraints()
        self._add_max_consecutive_work_days(max_days=6)
        self._add_max_consecutive_off_days(max_days=2)
        self._add_shift_consistency_constraints()
        self._add_night_shift_female_restriction()
        
        # --- Staffing coverage objective ---
        self._add_coverage_objective()
    
    def _add_leave_constraints(self):
        """Lock in leave/off requests from the tracker, and block Leave/Resign for everyone else."""
        leave_idx = self.shift_indices.get('Leave', len(self.working_shifts) - 2)
        resign_idx = self.shift_indices.get('Resign', len(self.working_shifts) - 1)
        
        # Track which (agent_idx, day_idx) pairs have explicit leave/resign requests
        leave_locked = set()
        
        for req in self.data.leave_requests:
            # Find agent index
            agent_idx = None
            for i, agent in enumerate(self.data.agents):
                if agent.id == req.employee_id:
                    agent_idx = i
                    break
            
            if agent_idx is None:
                continue
            
            # Find day index
            date_str = req.date.strftime('%Y-%m-%d')
            day_idx = None
            for d, ds in enumerate(self.data.dates):
                if ds == date_str:
                    day_idx = d
                    break
            
            if day_idx is None:
                continue
            
            if req.leave_type == 'Leave':
                self.model.Add(self.schedule_vars[(agent_idx, day_idx)] == leave_idx)
                leave_locked.add((agent_idx, day_idx))
            elif req.leave_type == 'Off':
                self.model.Add(self.schedule_vars[(agent_idx, day_idx)] == self.off_index)
                leave_locked.add((agent_idx, day_idx))
        
        # --- Block Leave/Resign for all agent-day pairs NOT in leave tracker ---
        num_agents = len(self.data.agents)
        num_days = len(self.data.dates)
        
        for a in range(num_agents):
            for d in range(num_days):
                if (a, d) not in leave_locked:
                    # This agent did NOT request leave/off on this day
                    # Block Leave and Resign shifts
                    self.model.Add(self.schedule_vars[(a, d)] != leave_idx)
                    self.model.Add(self.schedule_vars[(a, d)] != resign_idx)
    
    def _add_max_consecutive_work_days(self, max_days: int = 6):
        """Regulation 1: Max consecutive working days = 6."""
        num_agents = len(self.data.agents)
        num_days = len(self.data.dates)
        
        for a in range(num_agents):
            # For every window of (max_days + 1) consecutive days,
            # at least one must be OFF
            for d in range(num_days - max_days):
                is_off_vars = []
                for dd in range(d, d + max_days + 1):
                    is_off = self.model.NewBoolVar(f'is_off_a{a}_d{dd}_w{d}')
                    self.model.Add(
                        self.schedule_vars[(a, dd)] == self.off_index
                    ).OnlyEnforceIf(is_off)
                    self.model.Add(
                        self.schedule_vars[(a, dd)] != self.off_index
                    ).OnlyEnforceIf(is_off.Not())
                    is_off_vars.append(is_off)
                
                # At least one day in the window must be off
                self.model.Add(sum(is_off_vars) >= 1)
    
    def _add_max_consecutive_off_days(self, max_days: int = 2):
        """Regulation 3: Max consecutive off days = 2."""
        num_agents = len(self.data.agents)
        num_days = len(self.data.dates)
        
        for a in range(num_agents):
            # For every window of (max_days + 1) consecutive days,
            # at least one must be working (not OFF)
            for d in range(num_days - max_days):
                is_working_vars = []
                for dd in range(d, d + max_days + 1):
                    is_working = self.model.NewBoolVar(f'is_work_a{a}_d{dd}_w{d}')
                    self.model.Add(
                        self.schedule_vars[(a, dd)] != self.off_index
                    ).OnlyEnforceIf(is_working)
                    self.model.Add(
                        self.schedule_vars[(a, dd)] == self.off_index
                    ).OnlyEnforceIf(is_working.Not())
                    is_working_vars.append(is_working)
                
                self.model.Add(sum(is_working_vars) >= 1)
    
    def _add_shift_consistency_constraints(self):
        """
        Regulation 2: Avoid shift jumping.
        If an agent works shift A on day d and shift B on day d+1,
        A and B should be the same shift type (or one can be OFF).
        
        We allow transitions: same_shift->same_shift, any->OFF, OFF->any
        But not 03:00->20:00 or 20:00->03:00 without an OFF in between.
        """
        num_agents = len(self.data.agents)
        num_days = len(self.data.dates)
        
        off_idx = self.off_index
        leave_idx = self.shift_indices.get('Leave', len(self.working_shifts) - 2)
        resign_idx = self.shift_indices.get('Resign', len(self.working_shifts) - 1)
        
        # Find the indices for the two main working shifts
        shift_03_idx = None
        shift_20_idx = None
        for code, idx in self.shift_indices.items():
            if code not in ('OFF', 'Leave', 'Resign'):
                shift_info = self.data.shift_codes.get(code)
                if shift_info and shift_info.start_time:
                    if shift_info.start_time.hour == 3:
                        shift_03_idx = idx
                    elif shift_info.start_time.hour == 20:
                        shift_20_idx = idx
        
        if shift_03_idx is None or shift_20_idx is None:
            return
        
        for a in range(num_agents):
            for d in range(num_days - 1):
                # If day d is shift_03 and day d+1 is a working day,
                # then day d+1 must also be shift_03 (not shift_20)
                is_03_today = self.model.NewBoolVar(f'is03_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d)] == shift_03_idx
                ).OnlyEnforceIf(is_03_today)
                self.model.Add(
                    self.schedule_vars[(a, d)] != shift_03_idx
                ).OnlyEnforceIf(is_03_today.Not())
                
                is_working_tomorrow = self.model.NewBoolVar(f'iswork_tom_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] != off_idx
                ).OnlyEnforceIf(is_working_tomorrow)
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] == off_idx
                ).OnlyEnforceIf(is_working_tomorrow.Not())
                
                is_not_leave_tomorrow = self.model.NewBoolVar(f'notleave_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] != leave_idx
                ).OnlyEnforceIf(is_not_leave_tomorrow)
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] == leave_idx
                ).OnlyEnforceIf(is_not_leave_tomorrow.Not())
                
                is_not_resign_tomorrow = self.model.NewBoolVar(f'notresign_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] != resign_idx
                ).OnlyEnforceIf(is_not_resign_tomorrow)
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] == resign_idx
                ).OnlyEnforceIf(is_not_resign_tomorrow.Not())
                
                # If today is 03:00 AND tomorrow is working AND not leave AND not resign
                # Then tomorrow must be 03:00 (cannot jump to 20:00)
                both = self.model.NewBoolVar(f'both_a{a}_d{d}')
                self.model.AddBoolAnd([
                    is_03_today, is_working_tomorrow, 
                    is_not_leave_tomorrow, is_not_resign_tomorrow
                ]).OnlyEnforceIf(both)
                self.model.AddBoolOr([
                    is_03_today.Not(), is_working_tomorrow.Not(),
                    is_not_leave_tomorrow.Not(), is_not_resign_tomorrow.Not()
                ]).OnlyEnforceIf(both.Not())
                
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] == shift_03_idx
                ).OnlyEnforceIf(both)
                
                # Same for 20:00 shift
                is_20_today = self.model.NewBoolVar(f'is20_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d)] == shift_20_idx
                ).OnlyEnforceIf(is_20_today)
                self.model.Add(
                    self.schedule_vars[(a, d)] != shift_20_idx
                ).OnlyEnforceIf(is_20_today.Not())
                
                both2 = self.model.NewBoolVar(f'both2_a{a}_d{d}')
                self.model.AddBoolAnd([
                    is_20_today, is_working_tomorrow,
                    is_not_leave_tomorrow, is_not_resign_tomorrow
                ]).OnlyEnforceIf(both2)
                self.model.AddBoolOr([
                    is_20_today.Not(), is_working_tomorrow.Not(),
                    is_not_leave_tomorrow.Not(), is_not_resign_tomorrow.Not()
                ]).OnlyEnforceIf(both2.Not())
                
                self.model.Add(
                    self.schedule_vars[(a, d + 1)] == shift_20_idx
                ).OnlyEnforceIf(both2)
    
    def _add_night_shift_female_restriction(self):
        """
        Regulation 4: Night-shift restriction for female agents.
        Female agents should not be assigned to shifts starting at 20:00 or later.
        """
        shift_20_idx = None
        for code, idx in self.shift_indices.items():
            shift_info = self.data.shift_codes.get(code)
            if shift_info and shift_info.start_time and shift_info.start_time.hour == 20:
                shift_20_idx = idx
                break
        
        if shift_20_idx is None:
            return
        
        num_days = len(self.data.dates)
        
        for a, agent in enumerate(self.data.agents):
            if agent.gender == 'F':
                for d in range(num_days):
                    self.model.Add(
                        self.schedule_vars[(a, d)] != shift_20_idx
                    )
    
    def _add_coverage_objective(self):
        """
        Objective: Minimize the total gap between forecast demand and scheduled staff.
        
        For each day and hour, count how many agents are working during that hour,
        then minimize the absolute difference from the forecast.
        """
        num_agents = len(self.data.agents)
        num_days = len(self.data.dates)
        
        total_penalty = []
        
        # For simplicity, we'll track coverage at two key shift periods:
        # 03:00 shift covers approximately 03:00-12:00
        # 20:00 shift covers approximately 20:00-05:00
        
        shift_03_idx = None
        shift_20_idx = None
        for code, idx in self.shift_indices.items():
            shift_info = self.data.shift_codes.get(code)
            if shift_info and shift_info.start_time:
                if shift_info.start_time.hour == 3:
                    shift_03_idx = idx
                elif shift_info.start_time.hour == 20:
                    shift_20_idx = idx
        
        if shift_03_idx is None or shift_20_idx is None:
            return
        
        for d in range(num_days):
            date_str = self.data.dates[d]
            
            # Count agents on 03:00 shift
            agents_on_03 = []
            agents_on_20 = []
            
            for a in range(num_agents):
                is_on_03 = self.model.NewBoolVar(f'on03_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d)] == shift_03_idx
                ).OnlyEnforceIf(is_on_03)
                self.model.Add(
                    self.schedule_vars[(a, d)] != shift_03_idx
                ).OnlyEnforceIf(is_on_03.Not())
                agents_on_03.append(is_on_03)
                
                is_on_20 = self.model.NewBoolVar(f'on20_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d)] == shift_20_idx
                ).OnlyEnforceIf(is_on_20)
                self.model.Add(
                    self.schedule_vars[(a, d)] != shift_20_idx
                ).OnlyEnforceIf(is_on_20.Not())
                agents_on_20.append(is_on_20)
            
            # Target: roughly equal split between shifts
            # Based on forecast, we want about 20-22 working agents per day
            forecast_reqs = self.data.forecast.requirements.get(date_str, {})
            
            # Average demand during 03:00 shift hours (03-12)
            morning_demand = sum(forecast_reqs.get(h, 0) for h in range(3, 12)) // 9
            # Average demand during 20:00 shift hours (20-05)
            evening_demand = sum(forecast_reqs.get(h, 0) for h in list(range(20, 24)) + list(range(0, 5))) // 9
            
            morning_target = max(morning_demand, 8)
            evening_target = max(evening_demand, 8)
            
            # Minimize deviation from target
            count_03 = self.model.NewIntVar(0, num_agents, f'count03_d{d}')
            self.model.Add(count_03 == sum(agents_on_03))
            
            count_20 = self.model.NewIntVar(0, num_agents, f'count20_d{d}')
            self.model.Add(count_20 == sum(agents_on_20))
            
            # Absolute deviation for 03:00 shift
            dev_03 = self.model.NewIntVar(-num_agents, num_agents, f'dev03_d{d}')
            self.model.Add(dev_03 == count_03 - morning_target)
            abs_dev_03 = self.model.NewIntVar(0, num_agents, f'abs_dev03_d{d}')
            self.model.AddAbsEquality(abs_dev_03, dev_03)
            total_penalty.append(abs_dev_03)
            
            # Absolute deviation for 20:00 shift
            dev_20 = self.model.NewIntVar(-num_agents, num_agents, f'dev20_d{d}')
            self.model.Add(dev_20 == count_20 - evening_target)
            abs_dev_20 = self.model.NewIntVar(0, num_agents, f'abs_dev20_d{d}')
            self.model.AddAbsEquality(abs_dev_20, dev_20)
            total_penalty.append(abs_dev_20)
        
        # Also add penalty for uneven OFF distribution
        # Each agent should have ~8-9 off days in a 31-day month
        for a in range(num_agents):
            off_count = self.model.NewIntVar(0, num_days, f'off_count_a{a}')
            off_bools = []
            for d in range(num_days):
                is_off = self.model.NewBoolVar(f'off_a{a}_d{d}')
                self.model.Add(
                    self.schedule_vars[(a, d)] == self.off_index
                ).OnlyEnforceIf(is_off)
                self.model.Add(
                    self.schedule_vars[(a, d)] != self.off_index
                ).OnlyEnforceIf(is_off.Not())
                off_bools.append(is_off)
            
            self.model.Add(off_count == sum(off_bools))
            
            # Target 8-10 off days
            dev_off = self.model.NewIntVar(-num_days, num_days, f'dev_off_a{a}')
            self.model.Add(dev_off == off_count - 9)
            abs_dev_off = self.model.NewIntVar(0, num_days, f'abs_dev_off_a{a}')
            self.model.AddAbsEquality(abs_dev_off, dev_off)
            total_penalty.append(abs_dev_off)
        
        # Minimize total penalty
        self.model.Minimize(sum(total_penalty))
    
    def solve(self, time_limit_seconds: int = 60) -> bool:
        """Solve the model and extract results."""
        self.solver.parameters.max_time_in_seconds = time_limit_seconds
        self.solver.parameters.num_workers = 4
        
        status = self.solver.Solve(self.model)
        self.solve_status = status
        self.solve_time = self.solver.WallTime()
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            self._extract_results()
            return True
        
        return False
    
    def _extract_results(self):
        """Extract schedule from solver solution."""
        self.result_schedule = {}
        
        for a, agent in enumerate(self.data.agents):
            agent_schedule = {}
            for d, date_str in enumerate(self.data.dates):
                shift_idx = self.solver.Value(self.schedule_vars[(a, d)])
                shift_code = self.working_shifts[shift_idx]
                
                # Map back to display format
                if shift_code == 'OFF':
                    agent_schedule[date_str] = 'OFF'
                elif shift_code == 'Leave':
                    agent_schedule[date_str] = 'Leave'
                elif shift_code == 'Resign':
                    agent_schedule[date_str] = 'Resign'
                else:
                    # Show the shift start time
                    shift_info = self.data.shift_codes.get(shift_code)
                    if shift_info and shift_info.start_time:
                        agent_schedule[date_str] = shift_info.start_time.strftime('%H:%M')
                    else:
                        agent_schedule[date_str] = shift_code
            
            self.result_schedule[agent.id] = agent_schedule
    
    def get_results_json(self) -> dict:
        """Get results as a JSON-serializable dict."""
        agents_data = []
        for agent in self.data.agents:
            schedule = self.result_schedule.get(agent.id, {})
            agents_data.append({
                'id': agent.id,
                'name': agent.name,
                'role': agent.role,
                'channel': agent.channel,
                'gender': agent.gender,
                'schedule': schedule
            })
        
        # Calculate coverage stats
        coverage_stats = self._calculate_coverage()
        
        return {
            'agents': agents_data,
            'dates': self.data.dates,
            'shifts': self.working_shifts,
            'regulations': self.data.regulations,
            'coverage': coverage_stats,
            'solve_status': 'OPTIMAL' if self.solve_status == cp_model.OPTIMAL else 'FEASIBLE',
            'solve_time': round(self.solve_time, 2)
        }
    
    def _calculate_coverage(self) -> dict:
        """Calculate daily coverage statistics."""
        coverage = {}
        
        for d, date_str in enumerate(self.data.dates):
            day_stats = {
                'date': date_str,
                'shift_03_count': 0,
                'shift_20_count': 0,
                'off_count': 0,
                'leave_count': 0,
                'total_working': 0,
                'forecast_demand': sum(self.data.forecast.requirements.get(date_str, {}).values()) // 24
            }
            
            for agent in self.data.agents:
                shift = self.result_schedule.get(agent.id, {}).get(date_str, 'OFF')
                if shift == 'OFF':
                    day_stats['off_count'] += 1
                elif shift == 'Leave':
                    day_stats['leave_count'] += 1
                elif shift == '03:00':
                    day_stats['shift_03_count'] += 1
                    day_stats['total_working'] += 1
                elif shift == '20:00':
                    day_stats['shift_20_count'] += 1
                    day_stats['total_working'] += 1
                else:
                    day_stats['total_working'] += 1
            
            coverage[date_str] = day_stats
        
        return coverage
