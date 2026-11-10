"""
Project Management for D.A.M. Application
Handles project creation, storage, and data persistence
"""

import json
import os
from dataclasses import dataclass, asdict, field
from typing import Optional, List, Dict
from datetime import datetime
from pathlib import Path

@dataclass
class CPTData:
    """Stores extracted CPT data"""
    depth: List[float]
    qc: List[float]  # tip resistance
    fs: List[float]  # sleeve friction
    u2: List[float]  # pore water pressure
    units_qc: str = "MPa"
    units_fs: str = "kPa"
    units_u2: str = "kPa"
    units_depth: str = "m"
    boring_name: str = ""  # Name/ID of the boring (e.g., BH-01, CPT-A)
    channel_state: Dict[str, Dict] = field(default_factory=dict)  # Per-channel source image and digitising setup

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


@dataclass
class Borehole:
    """Store individual borehole/boring location within a project"""
    boring_name: str  # e.g., BH-01, CPT-A, SPT-01
    latitude: float
    longitude: float
    boring_type: str = "CPT"  # CPT, SPT, other
    depth: float = 0.0  # Drilling depth in meters
    notes: str = ""
    created_date: str = ""

    def __post_init__(self):
        if not self.created_date:
            self.created_date = datetime.now().isoformat()

    def to_dict(self):
        return {
            "boring_name": self.boring_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "boring_type": self.boring_type,
            "depth": self.depth,
            "notes": self.notes,
            "created_date": self.created_date,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)




@dataclass
class Project:
    """Represents a geotechnical project"""
    name: str
    created_date: str
    description: str = ""
    cpt_data: Optional[Dict] = None
    spt_data: Optional[Dict] = None
    boreholes: Optional[List[Dict]] = None

    def __post_init__(self):
        if self.created_date is None:
            self.created_date = datetime.now().isoformat()
        if self.boreholes is None:
            self.boreholes = []

    def to_dict(self):
        return {
            "name": self.name,
            "created_date": self.created_date,
            "description": self.description,
            "cpt_data": self.cpt_data,
            "spt_data": self.spt_data,
            "boreholes": self.boreholes or [],
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            name=data["name"],
            created_date=data.get("created_date", datetime.now().isoformat()),
            description=data.get("description", ""),
            cpt_data=data.get("cpt_data"),
            spt_data=data.get("spt_data"),
            boreholes=data.get("boreholes", []),
        )


class ProjectManager:
    """Manages project storage and retrieval"""

    def __init__(self, projects_dir: str = ".dam_projects"):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(exist_ok=True)
        self.projects_file = self.projects_dir / "projects.json"
        self.projects: Dict[str, Project] = {}
        self._load_projects()

    def _load_projects(self):
        """Load projects from storage"""
        if self.projects_file.exists():
            try:
                with open(self.projects_file, "r") as f:
                    data = json.load(f)
                    for proj_name, proj_data in data.items():
                        self.projects[proj_name] = Project.from_dict(proj_data)
            except Exception as e:
                print(f"Error loading projects: {e}")

    def _save_projects(self):
        """Save projects to storage"""
        try:
            with open(self.projects_file, "w") as f:
                data = {name: proj.to_dict() for name, proj in self.projects.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving projects: {e}")

    def create_project(self, name: str, description: str = "") -> Project:
        """Create a new project"""
        project = Project(
            name=name,
            created_date=datetime.now().isoformat(),
            description=description,
        )
        self.projects[name] = project
        self._save_projects()
        return project

    def get_project(self, name: str) -> Optional[Project]:
        """Get a project by name"""
        return self.projects.get(name)

    def list_projects(self) -> List[str]:
        """List all project names"""
        return list(self.projects.keys())

    def delete_project(self, name: str):
        """Delete a project"""
        if name in self.projects:
            del self.projects[name]
            self._save_projects()

    def save_cpt_data(self, project_name: str, cpt_data: CPTData):
        """Save CPT data to a project by boring name"""
        if project_name not in self.projects:
            return
        project = self.projects[project_name]
        if project.cpt_data is None:
            project.cpt_data = {}
        project.cpt_data[cpt_data.boring_name] = cpt_data.to_dict()
        self._save_projects()

    def load_cpt_data(self, project_name: str, boring_name: str) -> Optional[CPTData]:
        """Load CPT data from a project by boring name"""
        project = self.get_project(project_name)
        if not project or not project.cpt_data:
            return None

        # Check if old format (flat dict) or new format (nested by boring_name)
        if "depth" in project.cpt_data and boring_name in [project.cpt_data.get("boring_name", "")]:
            # Old format
            return CPTData.from_dict(project.cpt_data)
        elif boring_name in project.cpt_data:
            # New format
            return CPTData.from_dict(project.cpt_data[boring_name])
        return None

    def list_cpt_data(self, project_name: str) -> List[str]:
        """List all CPT boring names in a project"""
        project = self.get_project(project_name)
        if not project or not project.cpt_data:
            return []

        # Check if old format (flat dict with 'depth', 'qc' keys) or new format (nested by boring_name)
        if "depth" in project.cpt_data or "boring_name" in project.cpt_data:
            # Old format - single CPT stored as flat dict
            boring_name = project.cpt_data.get("boring_name", "Unknown")
            return [boring_name] if boring_name else []
        else:
            # New format - multiple CPTs stored by boring_name
            return [k for k in project.cpt_data.keys() if isinstance(project.cpt_data[k], dict)]

    def delete_cpt_data(self, project_name: str, boring_name: str):
        """Delete CPT data from a project by boring name"""
        project = self.get_project(project_name)
        if project and project.cpt_data and boring_name in project.cpt_data:
            del project.cpt_data[boring_name]
            self._save_projects()

    def get_cpt_data(self, project_name: str) -> Optional[CPTData]:
        """Get CPT data from a project (first one for backwards compatibility)"""
        project = self.get_project(project_name)
        if project and project.cpt_data:
            boring_names = list(project.cpt_data.keys())
            if boring_names:
                return CPTData.from_dict(project.cpt_data[boring_names[0]])
        return None

    def add_borehole(self, project_name: str, borehole: Borehole):
        """Add a borehole to a project"""
        if project_name in self.projects:
            if self.projects[project_name].boreholes is None:
                self.projects[project_name].boreholes = []
            self.projects[project_name].boreholes.append(borehole.to_dict())
            self._save_projects()

    def get_boreholes(self, project_name: str) -> List[Borehole]:
        """Get all boreholes from a project"""
        project = self.get_project(project_name)
        if project and project.boreholes:
            return [Borehole.from_dict(b) for b in project.boreholes]
        return []

    def delete_borehole(self, project_name: str, boring_name: str):
        """Delete a borehole from a project"""
        if project_name in self.projects:
            project = self.projects[project_name]
            if project.boreholes:
                project.boreholes = [b for b in project.boreholes if b.get("boring_name") != boring_name]
                self._save_projects()
