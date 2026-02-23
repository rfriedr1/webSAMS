# Delphi to Python Migration Map

## Data module (`_dm.pas`) methods already mapped

- `GetAllPlanned`, `GetAllInPrep`, `GetAllWaitingForGraph`, `GetAllWaitingForMeas`, `GetWaitingExpress`
  - Python: `SamsRepository.get_dashboard_counts/get_dashboard_tables`
- `AddNewProjectByUserNr`
  - Python: `SamsService.add_new_project_by_user_nr`
- `AddNewSampleByProjectNr`, `CreateBlankPrepRecord`, `CreateBlankTargetRecord`
  - Python: `SamsService.add_new_sample_by_project_nr` and `create_sample(..., with_blank_records=True)`
- `QuerySampleBySampleNr`, `QueryPrepStepsBySampleNr`, `QueryTargetInfoBySampleNr`, `GetSampleInfo`
  - Python: `SamsRepository.get_sample_details` + `/samples/{sample_nr}` page/API
- `TransferAgeFromTarget`
  - Python: `SamsService.transfer_age_from_target`
- `SetProjectStatusRunning`
  - Python: `SamsService.set_project_running`
- `CheckProjectStatus`
  - Python: `SamsService.check_project_status`

## Main form (`SAMS_Main.pas`) behavior already mapped

- User -> project -> sample navigation
  - Python pages: `/users`, `/users/{user_nr}/projects`, `/projects/{project_nr}/samples`, `/samples/{sample_nr}`
- Database search dialog (`FormDBSearch`)
  - Python page/API: `/search`, `/api/search`

## Next migration blocks (recommended order)

1. Import workflows (deferred; redesign and implementation planned for a later phase)
2. Lab task boards and batch assignment (prep/graph)
3. Magazine workflows (`GetMagazineData`, unpressed magazine handling)
4. Report export workflows and templated document generation
5. Email workflow migration (send confirmation + report notifications)
6. Storage location management (`StorageLocations.pas`)
7. Role-based auth and audit log replacement for desktop-only assumptions
