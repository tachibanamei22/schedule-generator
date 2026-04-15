"""
Data parser module — reads WFM Excel files into structured Python objects.
"""
import pandas as pd
from datetime import datetime, time, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Agent:
    id: str
    name: str
    role: str
    channel: str
    gender: str  # "M" or "F"


@dataclass
class ShiftCode:
    code: str
    start_time: Optional[time]
    end_time: Optional[time]
    is_leave: bool = False
    leave_type: str = ""
    
    @property
    def hours_covered(self) -> List[int]:
        """Return list of hour indices (0-23) this shift covers."""
        if self.is_leave or self.start_time is None or self.end_time is None:
            return []
        
        hours = []
        start_h = self.start_time.hour
        end_h = self.end_time.hour
        
        if end_h <= start_h:  # overnight shift
            for h in range(start_h, 24):
                hours.append(h)
            for h in range(0, end_h):
                hours.append(h)
        else:
            for h in range(start_h, end_h):
                hours.append(h)
        return hours
    
    @property
    def is_night_shift(self) -> bool:
        """A shift is a night shift if it covers hours between 22:00 and 06:00."""
        if self.is_leave or self.start_time is None:
            return False
        h = self.start_time.hour
        return h >= 18 or h < 6
    
    @property
    def shift_period(self) -> str:
        """Classify shift into morning/afternoon/night for shift-jumping detection."""
        if self.is_leave or self.start_time is None:
            return "off"
        h = self.start_time.hour
        if 3 <= h < 12:
            return "morning"
        elif 12 <= h < 18:
            return "afternoon"
        else:
            return "night"


@dataclass
class LeaveRequest:
    employee_id: str
    employee_name: str
    leave_type: str  # "Leave" or "Off"
    date: datetime


@dataclass
class ForecastData:
    """Hourly staffing requirements per day."""
    # date_str -> hour (0-23) -> required agents
    requirements: Dict[str, Dict[int, int]] = field(default_factory=dict)


@dataclass
class WFMData:
    agents: List[Agent]
    shift_codes: Dict[str, ShiftCode]
    leave_requests: List[LeaveRequest]
    forecast: ForecastData
    dates: List[str]  # list of date strings for the scheduling period
    regulations: List[str]


def parse_time_interval(interval_str: str) -> Tuple[Optional[time], Optional[time]]:
    """Parse time interval like '08:00-17:00' or '08:00:00'."""
    try:
        if '-' in str(interval_str):
            parts = str(interval_str).split('-')
            start = parts[0].strip()
            end = parts[1].strip()
            sh, sm = int(start.split(':')[0]), int(start.split(':')[1])
            eh, em = int(end.split(':')[0]), int(end.split(':')[1])
            return time(sh, sm), time(eh, em)
        else:
            # Handle datetime/time objects
            if hasattr(interval_str, 'hour'):
                return interval_str, None
            return None, None
    except:
        return None, None


def parse_shift_codes(wb) -> Dict[str, ShiftCode]:
    """Parse the Shift Code sheet."""
    ws = wb['Shift Code']
    shifts = {}
    
    leave_codes = {
        'CB', 'CBA', 'CIB', 'CKA', 'CL', 'CM', 'CAM', 'Leave', 'UL',
        'CH', 'CKG', 'CIM', 'CKM', 'CMBA', 'Sick', 'Permit', 'ITM', 'Alpha'
    }
    
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        code = str(row[0]).strip()
        interval = row[1] if len(row) > 1 else None
        
        if code in leave_codes or (interval and isinstance(interval, str) and not any(c.isdigit() for c in interval.split('-')[0] if ':' in interval)):
            shifts[code] = ShiftCode(
                code=code,
                start_time=None,
                end_time=None,
                is_leave=True,
                leave_type=str(interval) if interval else code
            )
        elif code == 'Day Off':
            shifts[code] = ShiftCode(code=code, start_time=None, end_time=None, is_leave=False)
        else:
            start_t, end_t = parse_time_interval(str(interval)) if interval else (None, None)
            shifts[code] = ShiftCode(code=code, start_time=start_t, end_time=end_t)
    
    # Ensure OFF and Day Off are present
    if 'OFF' not in shifts:
        shifts['OFF'] = ShiftCode(code='OFF', start_time=None, end_time=None)
    if 'Day Off' not in shifts:
        shifts['Day Off'] = ShiftCode(code='Day Off', start_time=None, end_time=None)
    
    return shifts


def _normalize_gender(raw: str) -> str:
    """
    Normalize gender codes to 'M' or 'F'.
    Handles: P/Perempuan → F, L/Laki-laki → M, M → M, F → F
    """
    if not raw:
        return "M"
    v = str(raw).strip().upper()
    if v in ("P", "PEREMPUAN", "WANITA", "FEMALE", "F"):
        return "F"
    if v in ("L", "LAKI", "LAKI-LAKI", "MALE", "M", "PRIA"):
        return "M"
    return "M"  # default


def parse_agents(wb) -> Tuple[List[Agent], List[str]]:
    """
    Parse agent list and schedule dates from the workbook.

    Supports two formats:
    - Custom WFM format: sheet named 'Input'
      Row 1 = headers (looks for a 'Gender' column if present)
      Row 2 = date values starting at col 6 (F)
      Row 3+ = agent rows: ID(A), Name(B), Role(C), Channel(D), [Detail/Gender(E)], ...
    - Simulation Schedule format: sheet named 'Call - Bahasa'
      Row 2 = dates starting at col 9
      Row 3 = headers; col 7 is Gender ('P'=Female, 'L'=Male)
      Row 4+ = agent rows
    """
    if 'Call - Bahasa' in wb.sheetnames:
        return _parse_agents_simulation(wb)
    return _parse_agents_custom(wb)


def _parse_agents_simulation(wb) -> Tuple[List[Agent], List[str]]:
    """Parse agents from the Simulation Schedule 'Call - Bahasa' sheet."""
    ws = wb['Call - Bahasa']
    agents = []
    dates = []

    # Row 2 has dates starting at column 9
    for col_idx in range(9, ws.max_column + 1):
        cell_val = ws.cell(row=2, column=col_idx).value
        if cell_val and isinstance(cell_val, datetime):
            dates.append(cell_val.strftime('%Y-%m-%d'))
        elif cell_val:
            break  # stop at first non-date

    # Row 4+ has agents (row 3 is headers)
    for row_idx in range(4, ws.max_row + 1):
        emp_id = ws.cell(row=row_idx, column=2).value   # NIP
        if emp_id is None:
            break

        emp_name = ws.cell(row=row_idx, column=3).value or f"Employee {emp_id}"
        role     = ws.cell(row=row_idx, column=4).value or "Agent"
        channel  = ws.cell(row=row_idx, column=5).value or "Call"
        gender   = _normalize_gender(ws.cell(row=row_idx, column=7).value)

        agents.append(Agent(
            id=str(emp_id),
            name=str(emp_name),
            role=str(role),
            channel=str(channel),
            gender=gender
        ))

    return agents, dates


def _parse_agents_custom(wb) -> Tuple[List[Agent], List[str]]:
    """Parse agents from the custom WFM 'Input' sheet."""
    ws = wb['Input']
    agents = []
    dates = []

    # --- Detect column layout from row 1 headers ---
    headers = {}
    for col_idx in range(1, ws.max_column + 1):
        h = ws.cell(row=1, column=col_idx).value
        if h is not None:
            headers[str(h).strip().lower()] = col_idx

    gender_col = headers.get('gender') or headers.get('jenis kelamin')

    # Find where dates start: row 2, scanning from col 6 onwards
    date_start_col = 6
    for col_idx in range(6, ws.max_column + 1):
        cell_val = ws.cell(row=2, column=col_idx).value
        if cell_val and isinstance(cell_val, (datetime, str)):
            date_start_col = col_idx
            break

    # Collect dates from row 2
    for col_idx in range(date_start_col, ws.max_column + 1):
        cell_val = ws.cell(row=2, column=col_idx).value
        if cell_val and isinstance(cell_val, datetime):
            dates.append(cell_val.strftime('%Y-%m-%d'))
        elif cell_val and isinstance(cell_val, str):
            dates.append(cell_val)
        elif cell_val is None:
            break

    # Collect agents from row 3+
    for row_idx in range(3, ws.max_row + 1):
        emp_id = ws.cell(row=row_idx, column=1).value
        if emp_id is None:
            break

        emp_name = ws.cell(row=row_idx, column=2).value or f"Employee {emp_id}"
        role     = ws.cell(row=row_idx, column=3).value or "Agent"
        channel  = ws.cell(row=row_idx, column=4).value or "Call"

        # Gender: read from detected column, else col 5 if it looks like a gender code
        if gender_col:
            raw_gender = ws.cell(row=row_idx, column=gender_col).value
            gender = _normalize_gender(raw_gender)
        else:
            # Try col 5 (Detail) as a fallback
            detail_val = str(ws.cell(row=row_idx, column=5).value or "")
            if detail_val.strip().upper() in ("M", "F", "P", "L"):
                gender = _normalize_gender(detail_val)
            else:
                gender = "M"  # default

        agents.append(Agent(
            id=str(emp_id),
            name=str(emp_name),
            role=str(role),
            channel=str(channel),
            gender=gender
        ))

    return agents, dates


def parse_leave_requests(wb) -> List[LeaveRequest]:
    """Parse the Leave/Req OFF Tracker sheet."""
    ws = wb['Leave_Req OFF Tracker']
    requests = []
    
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        
        emp_id = str(row[0])
        emp_name = str(row[1]) if row[1] else ""
        leave_type = str(row[4]) if row[4] else "Leave"
        date_val = row[5]
        
        if isinstance(date_val, datetime):
            date_str = date_val
        else:
            continue
        
        requests.append(LeaveRequest(
            employee_id=emp_id,
            employee_name=emp_name,
            leave_type=leave_type,
            date=date_str
        ))
    
    return requests


def parse_regulations(wb) -> List[str]:
    """Parse the Regulation sheet."""
    ws = wb['Regulation']
    regulations = []
    
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row and row[1]:
            regulations.append(str(row[1]))
    
    return regulations


def parse_forecast_from_expected(wb, dates: List[str]) -> ForecastData:
    """
    Build a simple forecast from the Expected Result sheet.
    For the Call channel, we can derive hourly requirements from the 
    expected schedule by counting how many agents work each hour.
    
    For a real system, this would come from the Simulation Schedule file.
    """
    forecast = ForecastData()
    
    # For now, create a reasonable demand profile for Call channel
    # Based on the patterns seen in the Data Forecast sheet
    # Peak hours 8-18, lower demand overnight
    base_demand = {
        0: 5, 1: 3, 2: 3, 3: 3, 4: 3, 5: 4,
        6: 6, 7: 8, 8: 12, 9: 15, 10: 16, 11: 16,
        12: 14, 13: 16, 14: 17, 15: 16, 16: 14, 17: 12,
        18: 10, 19: 9, 20: 9, 21: 8, 22: 6, 23: 5
    }
    
    for date_str in dates:
        forecast.requirements[date_str] = {}
        
        # Parse date to check if weekend
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            is_weekend = dt.weekday() >= 5
        except:
            is_weekend = False
        
        for hour in range(24):
            demand = base_demand[hour]
            if is_weekend:
                demand = max(2, int(demand * 0.75))  # 25% less on weekends
            forecast.requirements[date_str][hour] = demand
    
    return forecast


def load_wfm_data(filepath: str) -> WFMData:
    """Load and parse the WFM Data Excel file."""
    import openpyxl
    wb = openpyxl.load_workbook(filepath, data_only=True)
    
    agents, dates = parse_agents(wb)
    shift_codes = parse_shift_codes(wb)
    leave_requests = parse_leave_requests(wb)
    regulations = parse_regulations(wb)
    forecast = parse_forecast_from_expected(wb, dates)
    
    return WFMData(
        agents=agents,
        shift_codes=shift_codes,
        leave_requests=leave_requests,
        forecast=forecast,
        dates=dates,
        regulations=regulations
    )


def load_forecast_data(filepath: str, dates: List[str]) -> ForecastData:
    """
    Load forecast data from the Simulation Schedule Excel file.
    
    The 'Data Forecast' sheet has columns representing day 1, 2, ... 31 of a month
    (with placeholder dates like 2020-01-01). These map positionally to the actual
    schedule dates from the WFM Input sheet.
    
    Args:
        filepath: Path to the Simulation Schedule Excel file
        dates: Actual schedule dates from WFM Input sheet (e.g., ['2025-12-01', ...])
    
    Returns:
        ForecastData with demand mapped to the actual WFM dates
    """
    import openpyxl
    wb = openpyxl.load_workbook(filepath, data_only=True)
    
    forecast = ForecastData()
    
    try:
        ws = wb['Data Forecast']
        
        # --- Find the Bahasa Forecast section ---
        # Handles both "Bahasa (Forecast)" and "Time Interval Bahasa (Forecast)"
        header_row = None
        for row_idx in range(1, min(ws.max_row + 1, 30)):
            cell_val = ws.cell(row=row_idx, column=1).value
            if cell_val and 'Bahasa' in str(cell_val) and 'Forecast' in str(cell_val):
                header_row = row_idx
                break

        if header_row is None:
            # Fallback: typically at row 3 (Simulation Schedule) or row 6 (legacy)
            header_row = 3
        
        # --- Count how many day columns exist ---
        # The date/day columns start at column 2
        date_row = header_row + 1
        num_forecast_cols = 0
        for col_idx in range(2, ws.max_column + 1):
            cell_val = ws.cell(row=date_row, column=col_idx).value
            if cell_val is not None:
                num_forecast_cols += 1
            else:
                break
        
        if num_forecast_cols == 0:
            raise ValueError("No day columns found in Data Forecast sheet")
        
        # --- Extract hourly demand data ---
        # Data starts 4 rows after header (row with "0:00 - 1:00")
        data_start_row = header_row + 4
        
        # Map forecast columns positionally to the WFM dates
        # Column 2 (first data col) = dates[0], Column 3 = dates[1], etc.
        num_days_to_map = min(num_forecast_cols, len(dates))
        
        # Initialize requirements for each date
        for i in range(num_days_to_map):
            forecast.requirements[dates[i]] = {}
        
        for hour in range(24):
            row_idx = data_start_row + hour
            if row_idx > ws.max_row:
                break
            
            for day_idx in range(num_days_to_map):
                col_idx = day_idx + 2  # Data starts at column 2
                cell_val = ws.cell(row=row_idx, column=col_idx).value
                
                try:
                    demand = int(float(cell_val)) if cell_val is not None else 0
                except (ValueError, TypeError):
                    demand = 0
                
                forecast.requirements[dates[day_idx]][hour] = max(0, demand)
        
        # Fill any missing hours with 0
        for i in range(num_days_to_map):
            for hour in range(24):
                if hour not in forecast.requirements[dates[i]]:
                    forecast.requirements[dates[i]][hour] = 0
        
        # Fill any remaining WFM dates that don't have forecast data with 0
        for date_str in dates:
            if date_str not in forecast.requirements:
                forecast.requirements[date_str] = {h: 0 for h in range(24)}
        
        print(f"Loaded forecast: {num_days_to_map} days mapped, "
              f"{dates[0]} to {dates[num_days_to_map-1]}")
    
    except Exception as e:
        print(f"Warning: Could not parse Data Forecast sheet: {e}")
        # Fallback to default demand profile
        base_demand = {
            0: 5, 1: 4, 2: 3, 3: 4, 4: 4, 5: 5,
            6: 7, 7: 9, 8: 13, 9: 16, 10: 17, 11: 17,
            12: 15, 13: 17, 14: 18, 15: 17, 16: 15, 17: 12,
            18: 10, 19: 9, 20: 9, 21: 8, 22: 6, 23: 5
        }
        
        for date_str in dates:
            forecast.requirements[date_str] = {}
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                is_weekend = dt.weekday() >= 5
            except:
                is_weekend = False
            
            for hour in range(24):
                demand = base_demand[hour]
                if is_weekend:
                    demand = max(2, int(demand * 0.8))
                forecast.requirements[date_str][hour] = demand
    
    return forecast
