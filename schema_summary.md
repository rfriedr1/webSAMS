# Database: db_dmams (snapshot)

## Tables

- advisor_t(advisor, indexnr)  
# this table a list of last_name of advisors that can be assigned to a project
  
- calc_corr_t(calcset, corr_index, isobar_fact, isobar_err, isobar_off, std_ra, std_ra_err, std_ba, std_ba_err, bl_ra, bl_ra_err, scatter, a_slope, a_slope_off, b_slope, b_slope_off, time_corr, first_run, last_run, ra_nom, ba_nom, bg_const, bg_const_err, bl_const, bl_const_err, bl_const_mass, ra_norm, ba_norm)  
# this table stores the variables used during data-evaluation of a magazine
  
- calc_sample_t(calcset, sample_nr, prep_nr, target_nr, type, prep_bl, active, std_bl)  
# this table stores the variables used during data-evaluation of a sample
  
- calc_set_t(calcset, a_off, a_err_abs, a_err_rel, b_off, b_err_abs, b_err_rel, iso_off, iso_err_abs, iso_err_rel, isobar, magazine, date_calc, user_calc, charge, first_run, last_run, comment, fract, edit, deadtime, ba_nom, ra_nom, scatter, weighting, poisson, cycles, ra_norm, ba_norm)  
# this table stores the variables used during data-evaluation of a magazine
  
- fraction_t(fraction, indexnr)

- graphbatch_t(batch, batch_nr)  
# this table stores the name of a graphitization batch and the batch number

- magazine_t(name, last_changed)  
# this table stores the name of a magazine and the time when it was last changed

- material_t(material, indexnr)  
# this table stores a list of materials that are used as samples, every sample will be assigned a material

- measprog_t(magazine, sequence, position, recno, prepdate)  
# this table stores the measurement sequence of targets and their position in a magazine, it also stores when the targate was added to the sequence

- method_t(method, descr, indexnr)  
# this table stores the names of the available pretreatement methods, each prep will have pretreatment methods assigned to it

- preparation_t(prep_nr, sample_nr, batch, prep_comment, weight_start, weight_medium, weight_end, step1_method, step1_start, step1_end, step2_method, step2_start, step2_end, step3_method, step3_start, step3_end, step4_method, step4_start, step4_end, step5_method, step5_start, step5_end, cn_ratio, c_percent, n_percent, prep_end, stop, old_info, p_no_leftover, left_over, prep_start, weight_medium_2, weight_medium_date)  
# this table holds all infomration about the pre-treatement of a sample identified with the sample_nr, one sample can have multiple preparations/preps

- projectstatus_t(status, indexnr)  
# this table has a list of possible project statuses that can be assigned to a project

- projecttype_t(type, indexnr)  
# this table has a list of possible project types that can be assigned to a project

- project_t(project_nr, project, user_nr, invoice_nr, in_date, out_date, desired_date, priority, report_type, letter, project_comment, status, price, project_type, research, report, invoice, AuftragsNr, invoice_date, advisor, sample_storage_loc, FreeOfCharge, order_nr, supervisor, return_to_sender, returned_to_sender, prep_return_to_sender, prep_returned_to_sender)  
# this table holds all the information about a project, projects belong to users, projects can have samples

- reporttype_t(type, indexnr)  
# this table has a list of all possible report types that can be assigned to a project

- research_t(research, indexnr)  
# this table has a list of all possible research types that can be assigned to a project

- sampletype_t(type, indexnr, f14c, f14c_sig, d13c, d13c_sig, d13c_nom, blank, active)  
# this table has a list of all possible sample typesthat can be assigned to a sample

- sample_t(sample_nr, project_nr, photo, type, material, fraction, pre_sub_treat, weight, preparation, sampling_date, editable, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, residue, c14_age, c14_age_sig, av_fm, av_fm_sig, av_dc13, av_dc13_sig, av_dc13_irms, cal1sMin, cal1sMax, cal2sMin, cal2sMax, cal_curve, delta_R, calib, user_comment, old_info, MA_nr, s_no_leftover, s_storage_loc, prep_storage_loc, lab_comment, left_over, storage, CNIsotopA, DendroA, DendroHolzartA, CNIsotopAMoved)  
# this table holds all information about a sample identified by the sample_nr. samples belong to projects. samples have targets that store the measured data. a sample can have multiple preparateions and multiple targets.

- target_t(target_nr, sample_nr, prep_nr, magazine, position, precis, cycle_min, cycle_max, combustion, catalyst, cathode_nr, reactor_nr, co2_init, co2_final, hydro_init, hydro_final, react_time, target_comment, target_pressed, stop, old_info, meas_comment, fm, fm_sig, dc13, dc13_sig, calcset, editallowed, c14_age, c14_age_sig, cal1sMin, cal1sMax, cal2sMin, cal2sMax, graph_batch, graph_date, weight_combustion, weight, temp, graphitized, conc_c, cal_curve, conc_n, target_id, le_curr, he_curr)  
# this table holds all information about a target. a samples can have multiple preparation and a preparation can have multiple targets. The measurement date of a target can be parsed from the associated magazine name. The magazine name "MA251030" denotes the AMS instrument "MA", the year "25", the month "10" and the measurments day "30".

- user_t(user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, invoice, correspondance, user_comment, salutation, title, language)  
# this table holds all information a user (or a client), users can have projects


## Views

- advisor_v(advisor, indexnr)

- magazine_p(sample_nr, prep_nr, target_nr, target_id, magazine, position, precis, cycle_min, cycle_max, combustion, catalyst, cathode_nr, reactor_nr, co2_init, co2_final, hydro_init, hydro_final, react_time, target_comment, target_pressed, target_stop, target_old_info, meas_comment, fm, fm_sig, dc13, dc13_sig, calcset, editallowed, target_c14_age, target_c14_age_sig, target_cal1sMin, target_cal1sMax, target_cal2sMin, target_cal2sMax, target_weight, conc_n, graphitized, temp, conc_c, batch, prep_comment, weight_start, weight_medium, weight_end, step1_method, step1_start, step1_end, step2_method, step2_start, step2_end, step3_method, step3_start, step3_end, step4_method, step4_start, step4_end, step5_method, step5_start, step5_end, cn_ratio, c_percent, n_percent, prep_end, preparation_stop, preparation_old_info, photo, type, material, fraction, pre_sub_treat, sample_weight, preparation, sampling_date, editable, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, residue, sample_c14_age, sample_c14_age_sig, av_fm, av_fm_sig, av_dc13, av_dc13_sig, av_dc13_irms, sample_cal1sMin, sample_cal1sMax, sample_cal2sMin, sample_cal2sMax, cal_curve, delta_R, calib, sample_old_info, sample_user_comment, project_nr, project, invoice_nr, in_date, out_date, desired_date, priority, report_type, letter, project_comment, status, price, project_type, research, project_invoice, invoice_date, user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, user_invoice, correspondance, user_user_comment, language, title, salutation)

- preparation_p(prep_nr, sample_nr, project_nr, photo, type, material, fraction, pre_sub_treat, weight, preparation, sampling_date, editable, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, residue, c14_age, c14_age_sig, av_fm, av_fm_sig, av_dc13, av_dc13_sig, av_dc13_irms, cal1sMin, cal1sMax, cal2sMin, cal2sMax, cal_curve, delta_R, calib, old_info, user_comment, project, invoice_nr, in_date, out_date, desired_date, priority, report_type, letter, project_comment, status, price, project_type, research, project_invoice, user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, customer_invoice, correspondance, user_user_comment, language, title, salutation)

- preparation_v(sample_nr, prep_nr, batch, prep_comment, weight_start, weight_medium, weight_end, step1_method, step1_start, step1_end, step2_method, step2_start, step2_end, step3_method, step3_start, step3_end, step4_method, step4_start, step4_end, step5_method, step5_start, step5_end, cn_ratio, c_percent, n_percent, prep_end, stop, old_info, type, material, fraction, sampling_date, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, project_nr, project, priority, status, user_nr, first_name, last_name)

- project_p(project_nr, project, advisor, invoice_nr, in_date, out_date, desired_date, priority, report_type, letter, project_comment, status, price, project_type, research, projectinvoice, user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, customerinvoice, correspondance, user_user_comment, language, title, salutation)

- project_v(project_nr, project, last_name, first_name)

- sample_p(sample_nr, project_nr, photo, type, material, fraction, pre_sub_treat, weight, preparation, sampling_date, editable, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, residue, c14_age, c14_age_sig, av_fm, av_fm_sig, av_dc13, av_dc13_sig, av_dc13_irms, cal1sMin, cal1sMax, cal2sMin, cal2sMax, cal_curve, delta_R, calib, old_info, user_comment, project, advisor, invoice_nr, in_date, out_date, desired_date, priority, report_type, letter, project_comment, status, price, project_type, research, project_invoice, user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, customer_invoice, correspondance, user_user_comment, language, title, salutation)

- sample_v(sample_nr, type, material, fraction, pre_sub_treat, weight, sampling_date, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, residue, project_nr, project, priority, status, user_nr, first_name, last_name)

- target_calcset_p(sample_nr, prep_nr, target_nr, target_id, magazine, position, precis, cycle_min, cycle_max, combustion, catalyst, cathode_nr, reactor_nr, co2_init, co2_final, hydro_init, hydro_final, react_time, target_comment, target_pressed, target_stop, target_old_info, meas_comment, fm, fm_sig, dc13, dc13_sig, calcset, editallowed, target_c14_age, target_c14_age_sig, target_cal1sMin, target_cal1sMax, target_cal2sMin, target_cal2sMax, target_weight, conc_n, graphitized, temp, conc_c, date_calc, user_calc, batch, prep_comment, weight_start, weight_medium, weight_end, step1_method, step1_start, step1_end, step2_method, step2_start, step2_end, step3_method, step3_start, step3_end, step4_method, step4_start, step4_end, step5_method, step5_start, step5_end, cn_ratio, c_percent, n_percent, prep_end, preparation_stop, preparation_old_info, photo, type, material, fraction, pre_sub_treat, sample_weight, preparation, sampling_date, editable, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, residue, sample_c14_age, sample_c14_age_sig, av_fm, av_fm_sig, av_dc13, av_dc13_sig, av_dc13_irms, sample_cal1sMin, sample_cal1sMax, sample_cal2sMin, sample_cal2sMax, cal_curve, delta_R, calib, sample_old_info, sample_user_comment, project_nr, project, advisor, invoice_nr, in_date, out_date, desired_date, priority, report_type, letter, project_comment, status, price, project_type, research, project_invoice, invoice_date, user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, user_invoice, correspondance, user_user_comment, language, title, salutation)

- target_p(sample_nr, prep_nr, target_nr, target_id, magazine, position, precis, cycle_min, cycle_max, combustion, catalyst, cathode_nr, reactor_nr, co2_init, co2_final, hydro_init, hydro_final, react_time, target_comment, target_pressed, target_stop, target_old_info, meas_comment, fm, fm_sig, dc13, dc13_sig, calcset, editallowed, target_c14_age, target_c14_age_sig, target_cal1sMin, target_cal1sMax, target_cal2sMin, target_cal2sMax, target_weight, conc_n, graphitized, temp, conc_c, batch, prep_comment, weight_start, weight_medium, weight_end, step1_method, step1_start, step1_end, step2_method, step2_start, step2_end, step3_method, step3_start, step3_end, step4_method, step4_start, step4_end, step5_method, step5_start, step5_end, cn_ratio, c_percent, n_percent, prep_end, preparation_stop, preparation_old_info, photo, type, material, fraction, pre_sub_treat, sample_weight, preparation, sampling_date, editable, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, residue, sample_c14_age, sample_c14_age_sig, av_fm, av_fm_sig, av_dc13, av_dc13_sig, av_dc13_irms, sample_cal1sMin, sample_cal1sMax, sample_cal2sMin, sample_cal2sMax, cal_curve, delta_R, calib, sample_old_info, sample_user_comment, project_nr, project, advisor, invoice_nr, in_date, out_date, desired_date, priority, report_type, letter, project_comment, status, price, project_type, research, project_invoice, invoice_date, user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, user_invoice, correspondance, user_user_comment, language, title, salutation)
# this table holds all information about a target. a samples can have multiple preparation and a preparation can have multiple targets. The measurement date of a target can be parsed from the associated magazine name. The magazine name "MA251030" denotes the AMS instrument "MA", the year "25", the month "10" and the measurments day "30".

- target_v(sample_nr, prep_nr, target_nr, sample_id, target_id, magazine, position, precis, cycle_min, cycle_max, combustion, catalyst, cathode_nr, reactor_nr, co2_init, co2_final, hydro_init, hydro_final, react_time, target_comment, target_pressed, stop, old_info, meas_comment, fm, fm_sig, dc13, dc13_sig, calcset, editallowed, c14_age, c14_age_sig, cal1sMin, cal1sMax, cal2sMin, cal2sMax, weight, conc_n, graphitized, temp, conc_c, batch, type, material, fraction, sampling_date, not_tobedated, user_label, user_label_nr, user_desc1, user_desc2, project_nr, project, advisor, priority, status, user_nr, first_name, last_name)
# this table holds all information about a target. a samples can have multiple preparation and a preparation can have multiple targets. The measurement date of a target can be parsed from the associated magazine name. The magazine name "MA251030" denotes the AMS instrument "MA", the year "25", the month "10" and the measurments day "30".

- user_p(user_nr, first_name, last_name, organisation, institute, address_1, address_2, town, postcode, country, phone_1, phone_2, fax, email, www, account, invoice, correspondance, user_comment, language, title, salutation)


## Relationships

- preparation_t.sample_nr -> sample_t.sample_nr
- preparation_t.step1_method -> method_t.method
- preparation_t.step2_method -> method_t.method
- preparation_t.step3_method -> method_t.method
- preparation_t.step4_method -> method_t.method
- preparation_t.step5_method -> method_t.method
- project_t.invoice_nr -> user_t.user_nr
- project_t.project_type -> projecttype_t.type
- project_t.report_type -> reporttype_t.type
- project_t.research -> research_t.research
- project_t.status -> projectstatus_t.status
- project_t.user_nr -> user_t.user_nr
- sample_t.fraction -> fraction_t.fraction
- sample_t.material -> material_t.material
- sample_t.project_nr -> project_t.project_nr
- sample_t.type -> sampletype_t.type
- target_t.prep_nr -> preparation_t.prep_nr
- target_t.sample_nr -> preparation_t.sample_nr