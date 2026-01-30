@{
  RootModule = 'Tc.Admin.psm1'
  ModuleVersion = '0.1.0'
  GUID = '9f69b114-060c-4636-ba4b-22c34d5e6b1c'
  Author = 'Eric Ortego'
  CompanyName = 'AutomationWise'
  Copyright = '(c) Eric Ortego. All rights reserved.'
  Description = 'Opinionated admin toolkit (Azure, Graph, Intune, Autopilot).'
  PowerShellVersion = '7.0'

  NestedModules = @(
    'Modules/Tc.Admin.Automation.psm1',
    'Modules/Tc.Admin.Autopilot.psm1',
    'Modules/Tc.Admin.Azure.psm1',
    'Modules/Tc.Admin.Identity.psm1',
    'Modules/Tc.Admin.Intune.psm1'
  )

  FunctionsToExport = '*'
  CmdletsToExport = '*'
  VariablesToExport = '*'
  AliasesToExport = '*'

  PrivateData = @{
    PSData = @{
        Tags = @('admin', 'azure', 'intune', 'autopilot', 'graph')
        LicenseUri = ''
        ProjectUri = ''
        IconUri = ''
        ReleaseNotes = ''
    }
  }
}
