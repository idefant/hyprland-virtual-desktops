#pragma once

#ifndef VDESK_MANAGER_H
#define VDESK_MANAGER_H

#include "VirtualDesk.hpp"

class VirtualDeskManager {

  public:
    MonitorLayout overviewLayout(int id);
    VirtualDeskManager();
    std::unordered_map<int, std::shared_ptr<VirtualDesk>> vdesksMap;
    int                                                   lastDesk      = -1;
    std::unordered_map<int, std::string>                  vdeskNamesMap = {{1, "1"}};
    RememberLayoutConf                                    conf;
    const std::shared_ptr<VirtualDesk>&                   activeVdesk();
    void                                                  changeActiveDesk(std::string&, bool);
    void                                                  changeActiveDesk(int, bool, bool restoreFocus = true);
    void                                                  lastVisitedDesk();
    void                                                  prevDesk(bool backwardCycle);
    void                                                  nextDesk(bool cycle);
    void                                                  applyCurrentVDesk(bool restoreFocus = true);
    void                                                  rememberWindowFocus(PHLWINDOW window);
    int                                                   moveToDesk(std::string&, int vdeskId = -1);
    void                                                  loadLayoutConf();
    void                                                  invalidateAllLayouts();
    void                                                  reconcileMonitorLayout(const CSharedPointer<Monitor::CMonitor>& exclude = nullptr);
    WORKSPACEID                                           availableWorkspaceId(WORKSPACEID preferred, int vdeskId);
    void                                                  resetAllVdesks();
    void                                                  resetVdesk(const std::string& arg);
    void                                                  deleteInvalidMonitorsOnAllVdesks(const CSharedPointer<Monitor::CMonitor>&);
    void                                                  deleteInvalidMonitorsOnAllVdesks();
    int                                                   prevDeskId(bool backwardCycle);
    int                                                   nextDeskId(bool cycle);
    int                                                   getDeskIdFromName(const std::string& name, bool createIfNotFound = true);
    bool                                                  isDeskPopulated(int vdeskId);
    bool                                                  isWorkspaceOwnedByOtherVdesk(WORKSPACEID workspaceId, int vdeskId);

  private:
    std::unordered_map<int, PHLWINDOWREF> m_lastFocusedWindows;
    bool                              m_applyingDesk = false;
    int                               m_activeDeskKey = 1;
    bool                              confLoaded      = false;
    void                              cycleWorkspaces();
    std::shared_ptr<VirtualDesk>      getOrCreateVdesk(int vdeskId);
    std::vector<int>                  getValidDeskIds();
    int                               cycleDeskId(bool forward, bool allowCycle);
    CSharedPointer<Monitor::CMonitor> getFocusedMonitor();
};
#endif
